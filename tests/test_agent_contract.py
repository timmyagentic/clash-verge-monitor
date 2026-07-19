import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from clash_verge_traffic_ledger.__main__ import main
from clash_verge_traffic_ledger.audit import audit_traffic, build_evidence, find_case
from clash_verge_traffic_ledger.client import ControllerConfig
from clash_verge_traffic_ledger.contracts import SCHEMA_VERSION, envelope, render_json
from clash_verge_traffic_ledger.health import inspect_health
from clash_verge_traffic_ledger.models import TrafficDelta
from clash_verge_traffic_ledger.store import LedgerStore


MIB = 1024 * 1024


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


def seeded_store(path):
    store = LedgerStore(path)
    rows = []
    baseline_start = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    for offset in range(14):
        ts = baseline_start + timedelta(days=offset)
        rows.extend(
            [
                delta(ts, "StableApp", "stable.example", 5 * MIB, 95 * MIB),
                delta(ts, "SpikeApp", "spike.example", 1 * MIB, 9 * MIB),
                delta(ts, "unknown", "baseline-unknown.example", 1 * MIB, 1 * MIB),
            ]
        )

    window_start = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    for offset in range(7):
        ts = window_start + timedelta(days=offset)
        rows.extend(
            [
                delta(ts, "StableApp", "stable.example", 5 * MIB, 95 * MIB),
                delta(ts, "SpikeApp", "spike.example", 50 * MIB, 150 * MIB),
                delta(ts, "NewApp", "new.example", 50 * MIB, 50 * MIB),
                delta(ts, "unknown", "unknown.example", 50 * MIB, 150 * MIB),
            ]
        )
    store.record_deltas(rows)
    return store


class ContractTests(unittest.TestCase):
    def test_envelope_has_stable_top_level_fields(self):
        payload = envelope(
            "audit",
            {"verdict": "no_anomalies"},
            generated_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        )

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["operation"], "audit")
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(json.loads(render_json(payload))["data"]["verdict"], "no_anomalies")


class ReadOnlyStoreTests(unittest.TestCase):
    def test_read_only_store_queries_without_allowing_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            writable = seeded_store(path)
            readonly = LedgerStore(path, read_only=True)

            self.assertEqual(readonly.rollup_bounds()["last_date"], "2026-07-19")
            with self.assertRaisesRegex(RuntimeError, "read-only"):
                readonly.record_deltas([])
            self.assertGreater(writable.daily_total("2026-07-19")["total_bytes"], 0)

    def test_read_only_store_does_not_create_a_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.sqlite"
            with self.assertRaises(FileNotFoundError):
                LedgerStore(path, read_only=True)
            self.assertFalse(path.exists())


class HealthTests(unittest.TestCase):
    def test_health_separates_audit_readiness_from_sampling_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            seeded_store(path)
            now = datetime(2026, 7, 19, 12, 1, tzinfo=timezone.utc)

            data, warnings, actions = inspect_health(
                path,
                ControllerConfig(),
                now=now,
                max_sample_age_seconds=120,
                controller_probe=lambda config: {
                    "reachable": True,
                    "version": {"version": "test"},
                    "connection_count": 3,
                },
                service_state_reader=lambda label: "running",
            )

            self.assertEqual(data["status"], "healthy")
            self.assertTrue(data["audit_ready"])
            self.assertTrue(data["sampling_ready"])
            self.assertLess(data["database"]["sample_age_seconds"], 120)
            self.assertEqual(warnings, [])
            self.assertEqual(actions, [])

    def test_health_is_degraded_when_history_is_readable_but_sampling_is_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            seeded_store(path)

            def unavailable_controller(config):
                raise FileNotFoundError("controller socket missing")

            data, warnings, actions = inspect_health(
                path,
                ControllerConfig(),
                now=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
                controller_probe=unavailable_controller,
                service_state_reader=lambda label: "not loaded",
            )

            warning_codes = {item["code"] for item in warnings}
            self.assertEqual(data["status"], "degraded")
            self.assertTrue(data["audit_ready"])
            self.assertFalse(data["sampling_ready"])
            self.assertIn("controller_unreachable", warning_codes)
            self.assertIn("sampler_not_running", warning_codes)
            self.assertIn("sample_stale", warning_codes)
            self.assertTrue(actions)


class AuditTests(unittest.TestCase):
    def test_audit_detects_robust_spikes_new_subjects_and_unknown_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = seeded_store(Path(tmp) / "ledger.sqlite")

            data, warnings, actions = audit_traffic(store, "2026-07-19")
            codes = {case["code"] for case in data["cases"]}

            self.assertEqual(data["verdict"], "anomalies_detected")
            self.assertEqual(data["coverage"]["active_window_days"], 7)
            self.assertEqual(data["coverage"]["active_baseline_days"], 14)
            self.assertIn("sustained_process_spike", codes)
            self.assertIn("process_upload_spike", codes)
            self.assertIn("new_process", codes)
            self.assertIn("unknown_process_ratio", codes)
            self.assertTrue(all(case["case_id"].startswith("v1-20260719-7d-30d-") for case in data["cases"]))
            unknown_case = next(
                case for case in data["cases"] if case["code"] == "unknown_process_ratio"
            )
            self.assertEqual(unknown_case["baseline"]["daily_median_bytes"], 2 * MIB)
            self.assertEqual(warnings, [])
            self.assertEqual(actions[0]["code"], "inspect_case")

    def test_case_id_rebuilds_rollup_and_raw_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            seeded_store(path)
            store = LedgerStore(path, read_only=True)
            data, _, _ = audit_traffic(store, "2026-07-19")
            case_id = next(
                case["case_id"]
                for case in data["cases"]
                if case["code"] == "sustained_process_spike"
                and case["subject"]["type"] == "process"
            )

            case = find_case(store, case_id)
            evidence = build_evidence(store, case)

            self.assertEqual(evidence["case"]["case_id"], case_id)
            self.assertEqual(len(evidence["daily_series"]), 21)
            self.assertTrue(evidence["top_counterparties"])
            self.assertEqual(evidence["top_counterparties"][0]["counterpart"], "spike.example")

    def test_audit_cli_emits_json_and_never_creates_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            seeded_store(path)
            output = StringIO()
            with redirect_stdout(output):
                result = main(["audit", "--database", str(path), "--end-date", "2026-07-19"])

            payload = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(payload["schema_version"], "1")
            self.assertEqual(payload["operation"], "audit")

            missing = Path(tmp) / "missing.sqlite"
            output = StringIO()
            with redirect_stdout(output):
                result = main(["audit", "--database", str(missing)])
            self.assertEqual(result, 3)
            self.assertFalse(missing.exists())
            self.assertEqual(json.loads(output.getvalue())["errors"][0]["code"], "database_missing")


class MaintenanceTests(unittest.TestCase):
    def test_machine_maintenance_is_dry_run_until_apply_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            store = seeded_store(path)
            original_rows = store.raw_delta_count()

            output = StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "maintenance",
                        "--database",
                        str(path),
                        "--before",
                        "2026-07-13",
                        "--mode",
                        "compact",
                    ]
                )
            document = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertTrue(document["data"]["dry_run"])
            self.assertEqual(store.raw_delta_count(), original_rows)

            with redirect_stdout(StringIO()):
                result = main(
                    [
                        "maintenance",
                        "--database",
                        str(path),
                        "--before",
                        "2026-07-13",
                        "--mode",
                        "compact",
                        "--apply",
                    ]
                )
            self.assertEqual(result, 0)
            self.assertLess(store.raw_delta_count(), original_rows)
            self.assertGreater(store.daily_total("2026-06-29")["total_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
