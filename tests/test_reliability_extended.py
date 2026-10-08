import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace

from clash_verge_traffic_ledger.store import LedgerStore
from clash_verge_traffic_ledger.monitor import Sampler, DeltaComputer
from clash_verge_traffic_ledger.health import inspect_health
from clash_verge_traffic_ledger.client import ControllerConfig
from clash_verge_traffic_ledger.explore import explore
from clash_verge_traffic_ledger.audit import audit_traffic
from test_monitor import snapshot


class ExtendedReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = LedgerStore(Path(self.tmp.name) / "db.sqlite")
        self.now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)

    def test_idle_heartbeat_health_without_any_traffic(self):
        self.store.record_sample(self.now, [], interval=1)
        data, _, _ = inspect_health(
            self.store.path,
            ControllerConfig(),
            now=self.now + timedelta(seconds=2),
            service_label=None,
            check_controller=False,
        )
        self.assertTrue(data["sampling_ready"])
        self.assertIsNone(data["database"]["latest_sample"])
        self.assertFalse(data["audit_ready"])

    def test_failure_does_not_look_healthy_even_when_last_success_fresh(self):
        self.store.record_sample(self.now, [], interval=1)
        self.store.record_sample(
            self.now + timedelta(seconds=1), [], interval=1, error="TimeoutError"
        )
        data, _, _ = inspect_health(
            self.store.path,
            ControllerConfig(),
            now=self.now + timedelta(seconds=2),
            service_label=None,
            check_controller=False,
        )
        self.assertFalse(data["sampling_ready"])

    def test_core_reset_and_endpoint_change_rebaseline(self):
        class Client:
            identity = "a"
            last_totals = (0, 0)
            size = 0

            def connection_snapshots(self, **kwargs):
                return [snapshot("same", self.size, self.size)]

        client = Client()
        sampler = Sampler(client, self.store)
        sampler.sample_once(self.now)
        client.size = 100
        client.last_totals = (100, 100)
        sampler.sample_once(self.now + timedelta(seconds=1))
        client.size = 200
        client.last_totals = (1, 1)
        sampler.sample_once(self.now + timedelta(seconds=2))
        client.identity = "b"
        client.size = 300
        client.last_totals = (101, 101)
        sampler.sample_once(self.now + timedelta(seconds=3))
        self.assertEqual(self.store.daily_total("2026-10-08")["total_bytes"], 200)
        self.assertEqual(
            sum(e["kind"] == "baseline_reset" for e in self.store.recent_events()), 2
        )

    def test_core_comparison_exposes_missed_short_connections(self):
        class Client:
            last_totals = (0, 0)

            def connection_snapshots(self, **kwargs):
                return []

        client = Client()
        sampler = Sampler(client, self.store)
        sampler.sample_once(self.now)
        client.last_totals = (1024, 2048)
        sampler.sample_once(self.now + timedelta(seconds=1))
        meter = self.store.meter_comparison("2026-10-08", "2026-10-08")
        self.assertEqual(meter["unattributed_bytes"], 3072)
        self.assertEqual(meter["samples"], 1)

    def test_heartbeat_splits_midnight_without_overcount(self):
        end = datetime(2026, 10, 9, 0, 0, 1, tzinfo=timezone.utc)
        self.store.record_sample(end, [], interval=2, covered=2)
        days = self.store.coverage(
            "2026-10-08", "2026-10-09", now=end + timedelta(days=1)
        )["days"]
        self.assertEqual([d["covered_seconds"] for d in days], [1, 1])

    def test_failed_transaction_does_not_commit_traffic_or_baseline(self):
        class Client:
            size = 0

            def connection_snapshots(self, **kwargs):
                return [snapshot("a", self.size, 0)]

        client = Client()
        sampler = Sampler(client, self.store)
        sampler.sample_once(self.now)
        client.size = 100
        real = self.store._record_rows

        def fail_after_rows(c, rows):
            real(c, rows)
            if rows:
                raise sqlite3.OperationalError("simulated disk failure")

        with patch.object(self.store, "_record_rows", side_effect=fail_after_rows):
            with self.assertRaises(sqlite3.OperationalError):
                sampler.sample_once(self.now + timedelta(seconds=1))
        self.assertEqual(self.store.daily_total("2026-10-08")["total_bytes"], 0)
        client.size = 200
        sampler.sample_once(self.now + timedelta(seconds=2))
        self.assertEqual(self.store.daily_total("2026-10-08")["total_bytes"], 0)

    def test_routes_filters_and_injection_are_literal(self):
        computer = DeltaComputer()
        now = self.now
        items = [
            replace(snapshot(str(i), 0, 0, process="app"), chains=chain)
            for i, chain in enumerate([["DIRECT"], ["node", "group"], []])
        ]
        computer.compute(items, now)
        self.store.record_deltas(
            computer.compute([replace(x, upload=10, download=20) for x in items], now)
        )
        rows = explore(self.store, "2026-10-08", "2026-10-08", by="route")["rows"]
        self.assertEqual(
            {r["subject"]: r["total_bytes"] for r in rows},
            {"direct": 30, "proxy": 30, "unknown": 30},
        )
        self.assertEqual(
            explore(self.store, "2026-10-08", "2026-10-08", route="direct")["totals"][
                "total_bytes"
            ],
            30,
        )
        self.assertEqual(
            explore(self.store, "2026-10-08", "2026-10-08", process="' OR 1=1 --")[
                "rows"
            ],
            [],
        )
        with self.assertRaises(ValueError):
            explore(self.store, "2026-10-08", "2026-10-08", by="DROP TABLE")

    def test_legacy_read_is_nonmutating_and_migration_idempotent(self):
        with self.store.connect() as c:
            for table in (
                "hourly_traffic",
                "sample_minutes",
                "sampler_state",
                "sampler_events",
            ):
                c.execute("DROP TABLE " + table)
            c.execute("PRAGMA user_version=0")
        before = self.store.path.read_bytes()
        ro = LedgerStore(self.store.path, read_only=True)
        self.assertEqual(ro.coverage("2026-10-08", "2026-10-08")["status"], "unknown")
        self.assertEqual(before, self.store.path.read_bytes())
        LedgerStore(self.store.path)
        LedgerStore(self.store.path)
        with self.store.connect() as c:
            self.assertEqual(c.execute("pragma user_version").fetchone()[0], 2)

    def test_newer_schema_refused_without_modification(self):
        with self.store.connect() as c:
            c.execute("pragma user_version=999")
        before = self.store.path.read_bytes()
        with self.assertRaises(RuntimeError):
            LedgerStore(self.store.path)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_complete_day_requires_measured_coverage(self):
        with self.store.connect() as c:
            c.executemany(
                "INSERT INTO sample_minutes(minute,covered_seconds,successes) VALUES (?,60,60)",
                [(f"2026-10-07T{h:02}:{m:02}",) for h in range(24) for m in range(60)],
            )
        result = self.store.coverage("2026-10-07", "2026-10-07", now=self.now)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["ratio"], 1)
        self.assertEqual(
            self.store.coverage("2026-10-06", "2026-10-07", now=self.now)["status"],
            "partial",
        )

    def test_legacy_audit_never_calls_window_complete(self):
        data, warnings, _ = audit_traffic(self.store, "2026-10-07", now=self.now)
        self.assertEqual(data["coverage"]["window_end_status"], "unknown")
        self.assertEqual(data["verdict"], "insufficient_data")
        self.assertIn("sampling_coverage_incomplete", [w["code"] for w in warnings])

    def test_csv_formula_escaping(self):
        from clash_verge_traffic_ledger.dashboard import to_csv

        data = {
            "rows": [
                dict(subject="=1+1", upload_bytes=1, download_bytes=2, total_bytes=3)
            ],
            "coverage": {"status": "unknown"},
            "source": "raw",
        }
        self.assertIn("'=1+1", to_csv(data))


class NewConnectionTests(unittest.TestCase):
    def test_only_proven_new_connection_initial_bytes_are_counted(self):
        now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
        computer = DeltaComputer()
        items = [
            replace(snapshot("new", 100, 200), started_at=now - timedelta(seconds=0.5)),
            replace(snapshot("old", 10000, 20000), started_at=now - timedelta(hours=1)),
            snapshot("missing", 10000, 20000),
            replace(
                snapshot("future", 10000, 20000), started_at=now + timedelta(seconds=1)
            ),
        ]
        rows = computer.compute(items, now, since=now - timedelta(seconds=1))
        self.assertEqual(
            [(r.connection_id, r.upload_bytes, r.download_bytes) for r in rows],
            [("new", 100, 200)],
        )
        self.assertEqual(
            computer.compute(items, now + timedelta(seconds=1), since=now), []
        )

class PaginationTests(unittest.TestCase):
    def test_upload_sort_and_offset_do_not_change_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=LedgerStore(Path(tmp)/'db.sqlite')
            now=datetime(2026,10,8,12,tzinfo=timezone.utc)
            computer=DeltaComputer()
            computer.compute([snapshot(str(i),0,0,process=str(i)) for i in range(3)],now)
            store.record_deltas(computer.compute([snapshot(str(i),i*10,100,process=str(i)) for i in range(3)],now))
            data=explore(store,'2026-10-08','2026-10-08',sort='upload',limit=1,offset=1)
            self.assertEqual(data['rows'][0]['subject'],'1')
            self.assertEqual(data['totals']['total_bytes'],330)
            self.assertTrue(data['truncated'])
