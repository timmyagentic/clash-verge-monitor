import unittest
from datetime import datetime, timezone

from mihomo_flow_ledger.models import ConnectionSnapshot
from mihomo_flow_ledger.monitor import DeltaComputer


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


if __name__ == "__main__":
    unittest.main()

