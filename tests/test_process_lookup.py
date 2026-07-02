import unittest

from clash_verge_traffic_ledger.process_lookup import parse_lsof_process_names, choose_process_name


class ProcessLookupTests(unittest.TestCase):
    def test_parses_lsof_field_output(self):
        output = "p123\ncverge-mihomo-alpha\np456\ncCursor\n"

        self.assertEqual(parse_lsof_process_names(output), ["verge-mihomo-alpha", "Cursor"])
        self.assertEqual(choose_process_name(["verge-mihomo-alpha", "Cursor"]), "Cursor")

    def test_returns_first_name_when_only_core_process_is_seen(self):
        self.assertEqual(choose_process_name(["verge-mihomo-alpha"]), "verge-mihomo-alpha")
        self.assertIsNone(choose_process_name([]))


if __name__ == "__main__":
    unittest.main()
