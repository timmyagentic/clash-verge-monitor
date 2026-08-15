import unittest
from datetime import datetime, timezone

from clash_verge_traffic_ledger.models import ConnectionSnapshot
from clash_verge_traffic_ledger.monitor import DeltaComputer, Sampler


def snapshot(connection_id, upload, download, process="Cursor", host="api2.cursor.sh"):
    return ConnectionSnapshot(
        connection_id=connection_id,
        upload=upload,
        download=download,
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
    )


class DeltaComputerTests(unittest.TestCase):
    def test_first_seen_is_baseline_and_second_sample_counts_delta(self):
        computer = DeltaComputer()
        now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

        first = computer.compute([snapshot("a", 100, 200)], now)
        second = computer.compute([snapshot("a", 140, 260)], now)

        self.assertEqual(first, [])
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].upload_bytes, 40)
        self.assertEqual(second[0].download_bytes, 60)
        self.assertEqual(second[0].date, "2026-07-02")

    def test_removes_disappeared_connections_and_skips_resets(self):
        computer = DeltaComputer()
        now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

        computer.compute([snapshot("a", 100, 200), snapshot("b", 1, 1)], now)
        self.assertEqual(computer.compute([snapshot("a", 90, 250)], now), [])
        self.assertEqual(computer.compute([snapshot("b", 5, 5)], now), [])

    def test_reuses_last_known_process_for_the_same_connection(self):
        computer = DeltaComputer()
        now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

        computer.compute([snapshot("a", 100, 200, process="codex")], now)
        deltas = computer.compute([snapshot("a", 140, 260, process="unknown")], now)

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].process, "codex")

    def test_clears_cached_process_when_connection_disappears(self):
        computer = DeltaComputer()
        now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

        computer.compute([snapshot("a", 100, 200, process="codex")], now)
        computer.compute([], now)
        computer.compute([snapshot("a", 1, 1, process="unknown")], now)
        deltas = computer.compute([snapshot("a", 2, 2, process="unknown")], now)

        self.assertEqual(deltas[0].process, "unknown")


class SamplerAttributionTests(unittest.TestCase):
    def test_captures_one_process_table_per_sample(self):
        lookups = []

        class Client:
            def connection_snapshots(self, process_lookup_factory=None):
                lookups.append(process_lookup_factory())
                return []

        class Store:
            def record_deltas(self, deltas):
                self.deltas = list(deltas)

        process_lookup = lambda source_ip, port, network: "codex"
        sampler = Sampler(
            Client(),
            Store(),
            process_lookup_factory=lambda: process_lookup,
        )

        sampler.sample_once()

        self.assertEqual(lookups, [process_lookup])


class SamplerRetryTests(unittest.TestCase):
    def test_successful_polling_subtracts_sample_work_from_interval(self):
        class SuccessfulSampler(Sampler):
            def sample_once(self, now=None):
                return 0

        sampler = SuccessfulSampler(client=object(), store=object(), interval=1, max_backoff=4)
        clock = iter((10.0, 10.4))
        delays = []

        def stop_after_sleep(delay):
            delays.append(delay)
            raise StopIteration

        with self.assertRaises(StopIteration):
            sampler.run_forever(
                sleep=stop_after_sleep,
                monotonic=lambda: next(clock),
            )

        self.assertEqual(len(delays), 1)
        self.assertAlmostEqual(delays[0], 0.6)

    def test_transient_errors_back_off_without_exiting(self):
        class FailingSampler(Sampler):
            def sample_once(self, now=None):
                raise TimeoutError("controller timed out")

        sampler = FailingSampler(client=object(), store=object(), interval=1, max_backoff=4)
        delays = []
        errors = []

        def stop_after_three_sleeps(delay):
            delays.append(delay)
            if len(delays) == 3:
                raise StopIteration

        with self.assertRaises(StopIteration):
            sampler.run_forever(sleep=stop_after_three_sleeps, error_writer=errors.append)

        self.assertEqual(delays, [1, 2, 4])
        self.assertEqual(len(errors), 3)
        self.assertIn("TimeoutError", errors[0])


if __name__ == "__main__":
    unittest.main()
