import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from clash_verge_monitor.__main__ import main
from clash_verge_monitor.audit import audit_traffic, build_evidence, find_case
from clash_verge_monitor.client import ControllerConfig
from clash_verge_monitor.contracts import SCHEMA_VERSION, envelope, render_json
from clash_verge_monitor.health import inspect_health
from clash_verge_monitor.models import TrafficDelta
from clash_verge_monitor.store import LedgerStore


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
            seeded_store(path).record_sample(datetime(2026,7,19,12,tzinfo=timezone.utc), [], interval=1)
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
            seeded_store(path).record_sample(datetime(2026,7,19,12,tzinfo=timezone.utc), [], interval=1)

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

    def test_health_degrades_when_live_process_attribution_is_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            seeded_store(path).record_sample(datetime(2026,7,19,12,tzinfo=timezone.utc), [], interval=1)

            data, warnings, actions = inspect_health(
                path,
                ControllerConfig(),
                now=datetime(2026, 7, 19, 12, 1, tzinfo=timezone.utc),
                controller_probe=lambda config: {
                    "reachable": True,
                    "version": {"version": "test"},
                    "connection_count": 10,
                    "attribution": {
                        "known_connections": 2,
                        "unknown_connections": 8,
                        "known_ratio": 0.2,
                        "status": "degraded",
                    },
                },
                service_state_reader=lambda label: "running",
            )

            self.assertEqual(data["status"], "degraded")
            self.assertTrue(data["sampling_ready"])
            self.assertFalse(data["attribution_ready"])
            self.assertIn("process_attribution_degraded", {item["code"] for item in warnings})
            self.assertIn("inspect_process_attribution", {item["code"] for item in actions})


class AuditTests(unittest.TestCase):
    def test_audit_detects_robust_spikes_new_subjects_and_unknown_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = seeded_store(Path(tmp) / "ledger.sqlite")

            data, warnings, actions = audit_traffic(store, "2026-07-19")
            codes = {case["code"] for case in data["cases"]}

            self.assertEqual(data["verdict"], "anomalies_detected")
            self.assertEqual(data["coverage"]["active_window_days"], 7)
            self.assertEqual(data["coverage"]["active_baseline_days"], 14)
            self.assertEqual(data["window"]["observed_through"], "2026-07-19")
            self.assertIn("sustained_process_spike", codes)
            self.assertIn("process_upload_spike", codes)
            self.assertIn("new_process", codes)
            self.assertIn("unknown_process_ratio", codes)
            self.assertTrue(all(case["case_id"].startswith("v3-20260719-7d-30d-") for case in data["cases"]))
            unknown_case = next(
                case for case in data["cases"] if case["code"] == "unknown_process_ratio"
            )
            self.assertEqual(unknown_case["baseline"]["daily_median_bytes"], 2 * MIB)
            self.assertEqual({item["code"] for item in warnings}, {"process_attribution_degraded", "sampling_coverage_incomplete"})
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

    def test_tiny_chronic_unknown_share_is_not_a_traffic_anomaly(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            start = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
            store.record_deltas(
                [
                    delta(start + timedelta(days=offset), "unknown", "tiny.example", 0, 1)
                    for offset in range(37)
                ]
            )

            data, warnings, actions = audit_traffic(store, "2026-07-19")

            self.assertEqual(data["summary"]["total_bytes"], 7)
            self.assertEqual(data["verdict"], "insufficient_data")
            self.assertNotIn("unknown_process_ratio", {case["code"] for case in data["cases"]})
            self.assertEqual([w["code"] for w in warnings], ["sampling_coverage_incomplete"])
            self.assertEqual(actions, [])

    def test_chronic_unknown_share_is_a_coverage_diagnostic_not_an_anomaly(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            start = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
            store.record_deltas(
                [
                    delta(
                        start + timedelta(days=offset),
                        "unknown",
                        "chronic.example",
                        0,
                        200 * MIB,
                    )
                    for offset in range(37)
                ]
            )

            data, warnings, actions = audit_traffic(store, "2026-07-19")
            unknown_case = next(
                case for case in data["cases"] if case["code"] == "unknown_process_ratio"
            )

            self.assertEqual(unknown_case["severity"], "info")
            self.assertEqual(unknown_case["evidence"][0]["value"], 1.0)
            self.assertEqual(data["verdict"], "insufficient_data")
            self.assertEqual(data["coverage"]["process_attribution"]["status"], "degraded")
            self.assertIn("process_attribution_degraded", {item["code"] for item in warnings})
            self.assertIn("inspect_process_attribution", {item["code"] for item in actions})

    def test_current_day_audit_reports_cutoff_and_sample_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = seeded_store(Path(tmp) / "ledger.sqlite")

            data, warnings, _ = audit_traffic(
                store,
                "2026-07-19",
                now=datetime(2026, 7, 19, 12, 1, tzinfo=timezone.utc),
            )

            self.assertEqual(data["coverage"]["latest_sample"], "2026-07-19T12:00:00+00:00")
            self.assertEqual(data["coverage"]["sample_age_seconds"], 60.0)
            self.assertEqual(data["coverage"]["window_end_status"], "unknown")
            self.assertIn("partial_window_day", {item["code"] for item in warnings})

    def test_evidence_exposes_source_and_periodic_connection_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            store = seeded_store(path)
            rows = []
            for index, hour in enumerate((10, 11, 12)):
                ts = datetime(2026, 7, 19, hour, 56, tzinfo=timezone.utc)
                rows.append(
                    TrafficDelta(
                        ts=ts,
                        date=ts.date().isoformat(),
                        connection_id=f"periodic-{index}",
                        process="unknown",
                        host="periodic.example",
                        destination_ip="1.2.3.4",
                        source_ip="198.18.0.1",
                        source_port=51000 + index,
                        destination_port=443,
                        network="tcp",
                        connection_type="HTTPS",
                        chains=["Proxy"],
                        rule="MATCH",
                        upload_bytes=0,
                        download_bytes=200 * MIB,
                    )
                )
            for index, minute in enumerate((15, 30)):
                ts = datetime(2026, 7, 19, 13 + index, minute, tzinfo=timezone.utc)
                rows.append(
                    TrafficDelta(
                        ts=ts,
                        date=ts.date().isoformat(),
                        connection_id=f"localhost-noise-{index}",
                        process="unknown",
                        host="periodic.example",
                        destination_ip="1.2.3.4",
                        source_ip="127.0.0.1",
                        source_port=52000 + index,
                        destination_port=443,
                        network="tcp",
                        connection_type="HTTPS",
                        chains=["Proxy"],
                        rule="MATCH",
                        upload_bytes=0,
                        download_bytes=1,
                    )
                )
            store.record_deltas(rows)

            data, _, _ = audit_traffic(store, "2026-07-19")
            case = next(
                item
                for item in data["cases"]
                if item["code"] == "new_host" and item["subject"]["value"] == "periodic.example"
            )
            evidence = build_evidence(store, case)

            self.assertEqual(evidence["source_breakdown"][0]["source_ip"], "198.18.0.1")
            self.assertEqual(evidence["connection_pattern"]["connection_count"], 5)
            self.assertTrue(evidence["connection_pattern"]["periodic_start_pattern"])
            self.assertEqual(evidence["connection_pattern"]["dominant_start_minute"], 56)
            self.assertEqual(evidence["connection_pattern"]["dominant_start_count"], 3)
            self.assertEqual(
                evidence["connection_pattern"]["periodic_clusters"][0]["source_ip"],
                "198.18.0.1",
            )

    def test_evidence_rejects_unbounded_non_positive_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")

            with self.assertRaisesRegex(ValueError, "limit must be positive"):
                build_evidence(store, {}, limit=0)


class MaintenanceTests(unittest.TestCase):
    def test_latest_sample_does_not_regress_when_rollups_are_written_out_of_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            store = LedgerStore(path)
            recent = datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)
            older = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

            store.record_deltas([delta(recent, "App", "example.com", 1, 1)])
            store.record_deltas([delta(older, "App", "example.com", 1, 1)])

            self.assertEqual(store.latest_delta_timestamp(), recent.isoformat())

    def test_compaction_preserves_latest_sample_metadata_when_all_raw_rows_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            store = LedgerStore(path)
            sampled_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            store.record_deltas([delta(sampled_at, "OldApp", "old.example", 1, 1)])

            store.compact_raw_before("2026-07-02")

            self.assertEqual(store.raw_delta_count(), 0)
            self.assertEqual(store.latest_delta_timestamp(), sampled_at.isoformat())

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

    def test_legacy_retention_commands_are_dry_run_until_apply_is_explicit(self):
        for command in ("prune", "compact"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "ledger.sqlite"
                store = seeded_store(path)
                original_rows = store.raw_delta_count()
                arguments = [
                    command,
                    "--database",
                    str(path),
                    "--before",
                    "2026-07-13",
                ]

                with redirect_stdout(StringIO()):
                    self.assertEqual(main(arguments), 0)
                self.assertEqual(store.raw_delta_count(), original_rows)

                with redirect_stdout(StringIO()):
                    self.assertEqual(main([*arguments, "--apply"]), 0)
                self.assertLess(store.raw_delta_count(), original_rows)

    def test_retention_rejects_non_iso_cutoff_before_deleting_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = seeded_store(Path(tmp) / "ledger.sqlite")
            original_rows = store.raw_delta_count()

            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                store.delete_raw_before("tomorrow")

            self.assertEqual(store.raw_delta_count(), original_rows)

    def test_compaction_reclaims_database_file_bytes_and_keeps_rollups(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            store = LedgerStore(path)
            old_ts = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            recent_ts = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
            rows = [
                TrafficDelta(
                    ts=old_ts + timedelta(seconds=index),
                    date="2026-07-01",
                    connection_id=f"old-{index}",
                    process="OldApp",
                    host="old.example",
                    destination_ip="1.2.3.4",
                    source_ip="127.0.0.1",
                    source_port=50000 + index,
                    destination_port=443,
                    network="tcp",
                    connection_type="HTTPS",
                    chains=["x" * 2048],
                    rule="MATCH",
                    upload_bytes=1,
                    download_bytes=1,
                )
                for index in range(2000)
            ]
            rows.append(
                TrafficDelta(
                    ts=recent_ts,
                    date="2026-07-20",
                    connection_id="recent",
                    process="RecentApp",
                    host="recent.example",
                    destination_ip="1.2.3.4",
                    source_ip="127.0.0.1",
                    source_port=60000,
                    destination_port=443,
                    network="tcp",
                    connection_type="HTTPS",
                    chains=["Proxy"],
                    rule="MATCH",
                    upload_bytes=1,
                    download_bytes=1,
                )
            )
            store.record_deltas(rows)
            before = path.stat().st_size

            result = store.compact_raw_before("2026-07-20")
            after = path.stat().st_size

            self.assertEqual(result["deleted_raw_rows"], 2000)
            self.assertEqual(result["database_bytes_before"], before)
            self.assertEqual(result["database_bytes_after"], after)
            self.assertEqual(result["reclaimed_bytes"], before - after)
            self.assertGreater(result["reclaimed_bytes"], 0)
            self.assertLess(after, before)
            self.assertEqual(store.raw_delta_count(), 1)
            self.assertEqual(store.rollup_date_count(), 2)


if __name__ == "__main__":
    unittest.main()
