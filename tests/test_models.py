import unittest

from clash_verge_traffic_ledger.models import ConnectionSnapshot


class ConnectionSnapshotTests(unittest.TestCase):
    def test_uses_process_metadata_first(self):
        item = {
            "id": "abc",
            "upload": 10,
            "download": 20,
            "metadata": {
                "process": "Cursor",
                "processPath": "/Applications/Cursor.app/Contents/MacOS/Cursor",
                "host": "api2.cursor.sh",
                "sourceIP": "127.0.0.1",
                "sourcePort": "55000",
                "destinationIP": "1.2.3.4",
                "destinationPort": "443",
                "network": "tcp",
                "type": "HTTP",
            },
            "chains": ["Proxy"],
            "rule": "DOMAIN-SUFFIX",
        }

        snapshot = ConnectionSnapshot.from_api_item(item)

        self.assertEqual(snapshot.process, "Cursor")
        self.assertEqual(snapshot.host, "api2.cursor.sh")
        self.assertEqual(snapshot.source_port, 55000)
        self.assertEqual(snapshot.destination_port, 443)
        self.assertEqual(snapshot.chains, ["Proxy"])

    def test_uses_process_path_basename_then_lsof(self):
        path_item = {
            "id": "path",
            "metadata": {
                "processPath": "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT",
                "host": "",
                "destinationIP": "2.2.2.2",
            },
        }
        lsof_item = {
            "id": "lsof",
            "metadata": {
                "sourceIP": "127.0.0.1",
                "sourcePort": 62000,
                "destinationIP": "3.3.3.3",
            },
        }

        path_snapshot = ConnectionSnapshot.from_api_item(path_item)
        lsof_snapshot = ConnectionSnapshot.from_api_item(lsof_item, process_lookup=lambda port: "codex")

        self.assertEqual(path_snapshot.process, "ChatGPT")
        self.assertEqual(lsof_snapshot.process, "codex")
        self.assertEqual(lsof_snapshot.host, "3.3.3.3")


if __name__ == "__main__":
    unittest.main()
