import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from clash_verge_monitor.client import ControllerConfig, MihomoClient
from clash_verge_monitor.monitor import Sampler
from clash_verge_monitor.store import LedgerStore
from test_monitor import snapshot


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = LedgerStore(Path(self.tmp.name) / "ledger.sqlite")
        self.now = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)

    def test_idle_samples_are_healthy_but_legacy_is_unknown(self):
        self.assertEqual(
            self.store.coverage("2026-10-08", "2026-10-08")["status"], "unknown"
        )

        class Client:
            def connection_snapshots(self, **kwargs):
                return []

        sampler = Sampler(Client(), self.store)
        sampler.sample_once(self.now)
        sampler.sample_once(self.now + timedelta(seconds=1))
        state = self.store.sampling_state()
        self.assertEqual(state["status"], "ok")
        self.assertEqual(
            state["last_success"], (self.now + timedelta(seconds=1)).isoformat()
        )
        self.assertEqual(
            self.store.coverage("2026-10-08", "2026-10-08")["covered_seconds"], 1
        )

    def test_gap_rebaselines_instead_of_assigning_sleep_traffic_to_wake_minute(self):
        class Client:
            n = 0

            def connection_snapshots(self, **kwargs):
                self.n += 1
                return [snapshot("a", self.n * 100, self.n * 100)]

        sampler = Sampler(Client(), self.store)
        sampler.sample_once(self.now)
        sampler.sample_once(self.now + timedelta(seconds=1))
        sampler.sample_once(self.now + timedelta(hours=3))
        self.assertEqual(self.store.daily_total("2026-10-08")["total_bytes"], 200)
        self.assertEqual(
            self.store.coverage("2026-10-08", "2026-10-08")["covered_seconds"], 1
        )

    def test_failed_sample_visible_and_recovery_baselines(self):
        class Client:
            def connection_snapshots(self, **kwargs):
                raise TimeoutError("private controller detail")

        sampler = Sampler(Client(), self.store)
        with self.assertRaises(TimeoutError):
            sampler.sample_once(self.now)
        self.assertEqual(self.store.sampling_state()["status"], "error")
        self.assertNotIn("private", str(self.store.sampling_state()))

    def test_explicit_controller_never_falls_back(self):
        client = MihomoClient(ControllerConfig("/explicit/missing.sock"))
        with patch.object(client, "_get_unix", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                client.version()

    def test_automatic_discovery_retries_next_candidate(self):
        client = MihomoClient(ControllerConfig("auto"))
        with patch(
            "clash_verge_monitor.client.controller_candidates",
            return_value=["/old.sock", "/new.sock"],
        ):

            def fetch(path, headers):
                if client.resolved_controller == "/old.sock":
                    raise FileNotFoundError
                return {"version": "test"}

            with patch.object(client, "_get_unix", side_effect=fetch):
                self.assertEqual(client.version(), {"version": "test"})
                self.assertEqual(client.resolved_controller, "/new.sock")

    def test_second_writer_is_rejected(self):
        from clash_verge_monitor.locking import writer_lock

        with writer_lock(self.store.path):
            with self.assertRaises(RuntimeError):
                with writer_lock(self.store.path):
                    pass


if __name__ == "__main__":
    unittest.main()


class MaintenanceTests(unittest.TestCase):
    def test_backup_restore_and_non_overwrite(self):
        from clash_verge_monitor.maintenance import (
            backup_database,
            restore_database,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LedgerStore(root / "source.sqlite")
            store.record_sample(datetime.now(timezone.utc), [], interval=1)
            backup_database(store.path, root / "backup.sqlite")
            restore_database(root / "backup.sqlite", root / "restored.sqlite")
            self.assertFalse((root / "restored.sqlite").exists())
            restore_database(
                root / "backup.sqlite", root / "restored.sqlite", apply=True
            )
            self.assertEqual(
                LedgerStore(root / "restored.sqlite", read_only=True).sampling_state()[
                    "status"
                ],
                "ok",
            )
            with self.assertRaises(FileExistsError):
                backup_database(store.path, root / "backup.sqlite")

    def test_raw_retention_preserves_hourly_and_daily(self):
        from clash_verge_monitor.monitor import DeltaComputer
        from clash_verge_monitor.explore import explore

        with tempfile.TemporaryDirectory() as tmp:
            store = LedgerStore(Path(tmp) / "ledger.sqlite")
            computer = DeltaComputer()
            now = datetime(2026, 8, 1, tzinfo=timezone.utc)
            computer.compute([snapshot("x", 0, 0)], now)
            store.record_deltas(computer.compute([snapshot("x", 10, 20)], now))
            store.delete_raw_before("2026-08-02")
            self.assertEqual(
                explore(store, "2026-08-01", "2026-08-01")["totals"]["total_bytes"], 30
            )
            self.assertEqual(
                explore(store, "2026-08-01", "2026-08-01", by="connection")["totals"][
                    "total_bytes"
                ],
                0,
            )
