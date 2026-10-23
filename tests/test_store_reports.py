import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from clash_verge_monitor.models import TrafficDelta
from clash_verge_monitor.reports import export_csv, export_markdown, format_report
from clash_verge_monitor.store import LedgerStore


class StoreAndReportTests(unittest.TestCase):
    def test_records_deltas_and_rolls_up_daily_process_and_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.sqlite"
            store = LedgerStore(db_path)
            delta = TrafficDelta(
                ts=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                date="2026-07-02",
                connection_id="a",
                process="Cursor",
                host="api2.cursor.sh",
                destination_ip="1.2.3.4",
                source_ip="127.0.0.1",
                source_port=50000,
                destination_port=443,
                network="tcp",
                connection_type="HTTP",
                chains=["Proxy"],
                rule="MATCH",
                upload_bytes=40,
                download_bytes=60,
            )

            store.record_deltas([delta])
            store.record_deltas([delta])

            processes = store.daily_process("2026-07-02")
            hosts = store.daily_host("2026-07-02")

            self.assertEqual(processes[0]["process"], "Cursor")
            self.assertEqual(processes[0]["total_bytes"], 200)
            self.assertEqual(hosts[0]["host"], "api2.cursor.sh")
            self.assertEqual(hosts[0]["download_bytes"], 120)

    def test_exports_markdown_and_csv(self):
        rows = [
            {"process": "Cursor", "upload_bytes": 40, "download_bytes": 60, "total_bytes": 100},
            {"process": "codex", "upload_bytes": 10, "download_bytes": 15, "total_bytes": 25},
        ]

        markdown = format_report("2026-07-02", rows, title="By process", key="process")
        self.assertIn("By process", markdown)
        self.assertIn("Cursor", markdown)
        self.assertIn("100 B", markdown)

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "report.csv"
            md_path = Path(tmp) / "report.md"
            export_csv(csv_path, rows, key="process")
            export_markdown(md_path, "2026-07-02", rows, title="By process", key="process")

            with csv_path.open(newline="") as handle:
                exported = list(csv.DictReader(handle))
            self.assertEqual(exported[0]["process"], "Cursor")
            self.assertIn("Cursor", md_path.read_text())


if __name__ == "__main__":
    unittest.main()
