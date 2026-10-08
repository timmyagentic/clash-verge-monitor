import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace
from clash_verge_traffic_ledger.store import LedgerStore
from clash_verge_traffic_ledger.monitor import DeltaComputer
from clash_verge_traffic_ledger.overview import (
    overview_data,
    render_overview,
    render_details,
)
from test_monitor import snapshot


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = LedgerStore(Path(self.tmp.name) / "db.sqlite")
        self.now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
        c = DeltaComputer()
        items = [
            snapshot("p", 0, 0, process="codex"),
            replace(snapshot("d", 0, 0, process="direct"), chains=["DIRECT"]),
        ]
        c.compute(items, self.now)
        self.store.record_deltas(
            c.compute(
                [
                    replace(items[0], upload=100, download=200),
                    replace(items[1], upload=10, download=20),
                ],
                self.now,
            )
        )

    def test_real_totals_rankings_and_hour_buckets(self):
        d = overview_data(self.store, "2026-08-22")
        self.assertEqual(d["total"]["total_bytes"], 330)
        self.assertEqual(d["apps"][0]["subject"], "codex")
        self.assertEqual(d["upload"][12], 110)
        self.assertIsNone(d["upload"][11])
        self.assertFalse(d["healthy"])
        self.assertEqual(d["coverage"]["status"], "unknown")

    def test_route_filter_updates_all_dashboard_regions(self):
        d = overview_data(self.store, "2026-08-22", route="direct")
        self.assertEqual(d["total"]["total_bytes"], 30)
        self.assertEqual(d["apps"][0]["subject"], "direct")
        self.assertEqual(d["upload"][12], 10)
        self.assertEqual(sum(r["total_bytes"] for r in d["hosts"]), 30)

    def test_history_and_empty_dates_do_not_fabricate_samples(self):
        d = overview_data(self.store, "2026-08-22", "history")
        self.assertEqual(len(d["labels"]), 7)
        self.assertEqual(d["upload"][-1], 110)
        self.assertIsNone(d["upload"][0])
        html = render_overview(self.store, "2026-08-21")
        self.assertIn("所选日期没有流量记录", html)
        self.assertIn("暂无记录</span>", html)
        self.assertNotIn("<strong>0<span>B</span>", html)
        self.assertNotIn('class="chart-empty" hidden', html)

    def test_shell_has_accessible_navigation_and_no_diagnostic_form(self):
        html = render_overview(self.store, "2026-08-22")
        self.assertIn('aria-label="应用程序"', html)
        self.assertIn("<canvas", html)
        self.assertNotIn('name="process"', html)
        self.assertIn('id="collection"', html)
        self.assertIn("assets/dashboard.js", html)

    def test_detail_filters_and_escape_preserved(self):
        options = dict(
            start="2026-08-22",
            end="2026-08-22",
            by="process",
            process='"<script>',
            host="",
            route="",
            sort="upload",
            offset=0,
        )
        html = render_details(self.store, "2026-08-22", options)
        self.assertNotIn('"<script>', html)
        self.assertIn("导出当前页", html)
        self.assertIn("历史覆盖未知", html)
