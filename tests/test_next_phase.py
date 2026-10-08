import plistlib
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from clash_verge_traffic_ledger.anomalies import detect_anomalies
from clash_verge_traffic_ledger.__main__ import build_parser, main
from clash_verge_traffic_ledger.models import TrafficDelta
from clash_verge_traffic_ledger.service import build_launchd_plist, service_state
from clash_verge_traffic_ledger.status import build_status, format_status
from clash_verge_traffic_ledger.store import LedgerStore
from clash_verge_traffic_ledger.web import render_dashboard


def delta(ts, process, host, upload, download):
    return TrafficDelta(
        ts=ts,
        date=ts.date().isoformat(),
        connection_id=f"{process}-{host}-{ts.isoformat()}",
        process=process,
        host=host,
        destination_ip="1.2.3.4",
        source_ip="127.0.0.1",
        source_port=50000,
        destination_port=443,
        network="tcp",
        connection_type="HTTP",
        chains=["Proxy"],
        rule="MATCH",
        upload_bytes=upload,
        download_bytes=download,
    )


class ServiceTests(unittest.TestCase):
    def test_builds_launchd_plist_for_sampler(self):
        payload = build_launchd_plist(
            label="com.example.ledger",
            python="/tmp/venv/bin/python",
            working_directory="/tmp/project",
            database="/tmp/project/data/ledger.sqlite",
            controller="/tmp/verge/verge-mihomo.sock",
            interval=2.5,
            stdout_path="/tmp/project/data/ledger.out.log",
            stderr_path="/tmp/project/data/ledger.err.log",
        )

        plist = plistlib.loads(payload)

        self.assertEqual(plist["Label"], "com.example.ledger")
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(plist["KeepAlive"])
        self.assertEqual(plist["WorkingDirectory"], "/tmp/project")
        self.assertEqual(plist["StandardOutPath"], "/tmp/project/data/ledger.out.log")
        self.assertEqual(plist["StandardErrorPath"], "/tmp/project/data/ledger.err.log")
        self.assertEqual(
            plist["ProgramArguments"],
            [
                "/tmp/venv/bin/python",
                "-m",
                "clash_verge_traffic_ledger",
                "run",
                "--interval",
                "2.5",
                "--max-backoff",
                "30",
                "--database",
                "/tmp/project/data/ledger.sqlite",
                "--controller",
                "/tmp/verge/verge-mihomo.sock",
            ],
        )

    def test_launchd_uses_a_secret_file_path_instead_of_secret_contents(self):
        payload = build_launchd_plist(
            label="com.example.ledger",
            python="/tmp/venv/bin/python",
            working_directory="/tmp/project",
            database="/tmp/project/data/ledger.sqlite",
            controller="http://127.0.0.1:9090",
            interval=1,
            stdout_path="/tmp/ledger.out.log",
            stderr_path="/tmp/ledger.err.log",
            secret_file="/tmp/controller.secret",
        )

        arguments = plistlib.loads(payload)["ProgramArguments"]
        self.assertIn("--secret-file", arguments)
        self.assertIn("/tmp/controller.secret", arguments)
        self.assertNotIn("super-secret", payload.decode("utf-8"))

    def test_reads_launchd_service_state_without_mutating_service(self):
        def running_runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="state = running\n", stderr="")

        def missing_runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 3, stdout="", stderr="Could not find service")

        self.assertEqual(service_state("com.example.ledger", runner=running_runner), "running")
        self.assertEqual(service_state("com.example.ledger", runner=missing_runner), "not loaded")


class StoreStatusRetentionTests(unittest.TestCase):
    def test_status_reads_latest_sample_total_and_prunes_raw_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.sqlite"
            store = LedgerStore(db_path)
            previous = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
            current = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
            store.record_deltas(
                [
                    delta(previous, "Cursor", "api.cursor.sh", 10, 15),
                    delta(current, "Cursor", "api.cursor.sh", 40, 60),
                    delta(current, "unknown", "unknown.example", 20, 30),
                ]
            )

            status = build_status(store, "2026-07-02", service_label="com.example.ledger", service_state_reader=lambda label: "running")

            self.assertTrue(status.database_exists)
            self.assertEqual(status.service_label, "com.example.ledger")
            self.assertEqual(status.service_state, "running")
            self.assertEqual(status.latest_sample, "2026-07-02T12:00:00+00:00")
            self.assertEqual(status.raw_delta_rows, 3)
            self.assertEqual(status.today_upload_bytes, 60)
            self.assertEqual(status.today_download_bytes, 90)
            self.assertEqual(status.today_total_bytes, 150)

            deleted = store.delete_raw_before("2026-07-02")

            self.assertEqual(deleted, 1)
            self.assertEqual(store.raw_delta_count(), 2)
            self.assertEqual(store.daily_total("2026-07-01")["total_bytes"], 25)

    def test_compacts_raw_deltas_before_date_while_daily_rollups_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            previous = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
            current = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
            store.record_deltas(
                [
                    delta(previous, "Cursor", "api.cursor.sh", 10, 15),
                    delta(current, "Cursor", "api.cursor.sh", 40, 60),
                ]
            )

            result = store.compact_raw_before("2026-07-02")

            self.assertEqual(result["deleted_raw_rows"], 1)
            self.assertEqual(result["remaining_raw_rows"], 1)
            self.assertEqual(result["preserved_rollup_dates"], 2)
            self.assertEqual(store.daily_total("2026-07-01")["total_bytes"], 25)


class AnomalyTests(unittest.TestCase):
    def test_reports_unknown_ratio_high_usage_and_process_spike(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            previous = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
            current = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
            store.record_deltas(
                [
                    delta(previous, "Cursor", "api.cursor.sh", 20, 30),
                    delta(current, "Cursor", "api.cursor.sh", 100, 120),
                    delta(current, "unknown", "unknown.example", 40, 40),
                ]
            )

            anomalies = detect_anomalies(
                store,
                "2026-07-02",
                byte_threshold=100,
                unknown_ratio_threshold=0.25,
                spike_multiplier=2.0,
                min_unknown_bytes=0,
            )
            codes = [item.code for item in anomalies]

            self.assertIn("high_process_usage", codes)
            self.assertIn("high_host_usage", codes)
            self.assertIn("unknown_process_ratio", codes)
            self.assertIn("process_spike", codes)

    def test_tiny_unknown_share_is_not_reported_as_an_anomaly_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            current = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
            store.record_deltas(
                [
                    delta(current, "Cursor", "api.cursor.sh", 1, 1),
                    delta(current, "unknown", "unknown.example", 1, 1),
                ]
            )

            anomalies = detect_anomalies(
                store,
                "2026-07-02",
                byte_threshold=500 * 1024 * 1024,
                unknown_ratio_threshold=0.25,
                spike_multiplier=3.0,
            )

            self.assertNotIn("unknown_process_ratio", {item.code for item in anomalies})


class WebDashboardTests(unittest.TestCase):
    def test_renders_read_only_dashboard_with_status_and_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            current = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
            store.record_deltas([delta(current, "Cursor", "api.cursor.sh", 40, 60)])
            status = build_status(store, "2026-07-02")

            html = render_dashboard(store, "2026-07-02", status)

            self.assertIn("<title>Clash Verge Traffic Ledger</title>", html)
            self.assertIn("2026-07-02", html)
            self.assertIn("Cursor", html)
            self.assertIn("api.cursor.sh", html)
            self.assertIn("100 B", html)
            self.assertNotIn('method="post"', html.lower())

    def test_dashboard_includes_trend_and_anomaly_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            previous = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
            current = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
            store.record_deltas(
                [
                    delta(previous, "Cursor", "api.cursor.sh", 10, 10),
                    delta(current, "Cursor", "api.cursor.sh", 100, 120),
                    delta(
                        current,
                        "unknown",
                        "unknown.example",
                        60 * 1024 * 1024,
                        60 * 1024 * 1024,
                    ),
                ]
            )

            html = render_dashboard(
                store,
                "2026-07-02",
                build_status(store, "2026-07-02"),
                anomaly_byte_threshold=100,
            )

            self.assertIn("Daily trend", html)
            self.assertIn("异常提示说明", html)
            self.assertIn("2026-07-01", html)
            self.assertIn("2026-07-02", html)
            self.assertIn("应用归属缺口", html)


class CliParserTests(unittest.TestCase):
    def test_next_phase_commands_are_registered(self):
        parser = build_parser()

        self.assertEqual(parser.parse_args(["status"]).command, "status")
        self.assertEqual(parser.parse_args(["anomalies"]).command, "anomalies")
        self.assertEqual(parser.parse_args(["health"]).command, "health")
        self.assertEqual(parser.parse_args(["audit"]).command, "audit")
        self.assertEqual(
            parser.parse_args(["evidence", "--case-id", "v1-20260719-7d-30d-000000000000"]).command,
            "evidence",
        )
        self.assertEqual(
            parser.parse_args(["maintenance", "--before", "2026-07-01"]).command,
            "maintenance",
        )
        self.assertEqual(parser.parse_args(["web"]).command, "web")
        self.assertEqual(parser.parse_args(["prune", "--before", "2026-07-01"]).command, "prune")
        self.assertEqual(parser.parse_args(["compact", "--before", "2026-07-01"]).command, "compact")
        self.assertEqual(parser.parse_args(["install-service", "--no-load"]).command, "install-service")
        self.assertEqual(parser.parse_args(["uninstall-service"]).command, "uninstall-service")

    def test_status_command_includes_service_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = build_status(
                LedgerStore(Path(tmp) / "ledger.sqlite"),
                "2026-07-02",
                service_label="com.example.ledger",
                service_state_reader=lambda label: "not loaded",
            )

        rendered = format_status(status, "2026-07-02")

        self.assertIn("Service label: com.example.ledger", rendered)
        self.assertIn("Service state: not loaded", rendered)

    def test_install_service_no_load_writes_plist_and_creates_log_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "missing" / "ledger.sqlite"
            plist = root / "agent.plist"

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(
                    [
                        "install-service",
                        "--database",
                        str(database),
                        "--plist",
                        str(plist),
                        "--no-load",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertTrue(database.parent.exists())
            self.assertTrue(plist.exists())

    def test_install_service_rejects_plaintext_secret_before_writing_plist(self):
        with tempfile.TemporaryDirectory() as tmp:
            plist = Path(tmp) / "agent.plist"

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = main(
                    [
                        "install-service",
                        "--plist",
                        str(plist),
                        "--secret",
                        "super-secret",
                        "--no-load",
                    ]
                )

            self.assertEqual(result, 1)
            self.assertFalse(plist.exists())


if __name__ == "__main__":
    unittest.main()
