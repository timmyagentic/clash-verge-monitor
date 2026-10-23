import unittest

from clash_verge_monitor.client import MihomoClient
from clash_verge_monitor.models import ConnectionSnapshot


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
        lsof_snapshot = ConnectionSnapshot.from_api_item(
            lsof_item,
            process_lookup=lambda source_ip, port, network: "codex",
        )

        self.assertEqual(path_snapshot.process, "ChatGPT")
        self.assertEqual(lsof_snapshot.process, "codex")
        self.assertEqual(lsof_snapshot.host, "3.3.3.3")

    def test_uses_endpoint_lookup_for_tun_and_udp_connections(self):
        calls = []
        item = {
            "id": "tun-udp",
            "metadata": {
                "sourceIP": "198.18.0.1",
                "sourcePort": 53530,
                "destinationIP": "8.8.8.8",
                "destinationPort": 443,
                "network": "udp",
            },
        }

        snapshot = ConnectionSnapshot.from_api_item(
            item,
            process_lookup=lambda source_ip, port, network: calls.append(
                (source_ip, port, network)
            )
            or "ChatGPT",
        )

        self.assertEqual(snapshot.process, "ChatGPT")
        self.assertEqual(calls, [("198.18.0.1", 53530, "udp")])

    def test_treats_unknown_metadata_as_missing_and_uses_fallback(self):
        item = {
            "id": "unknown-process",
            "metadata": {
                "process": "UNKNOWN",
                "sourceIP": "198.18.0.1",
                "sourcePort": 54000,
                "network": "tcp",
            },
        }

        snapshot = ConnectionSnapshot.from_api_item(
            item,
            process_lookup=lambda source_ip, port, network: "Cursor",
        )

        self.assertEqual(snapshot.process, "Cursor")

    def test_malformed_metadata_degrades_to_unknown_instead_of_crashing(self):
        snapshot = ConnectionSnapshot.from_api_item({"id": "malformed", "metadata": "bad"})

        self.assertEqual(snapshot.process, "unknown")
        self.assertEqual(snapshot.connection_id, "malformed")


class ClientAttributionTests(unittest.TestCase):
    def test_captures_process_table_after_controller_snapshot_and_only_when_needed(self):
        events = []

        class Client(MihomoClient):
            def raw_connections(self):
                events.append("controller")
                return {
                    "connections": [
                        {
                            "id": "tun",
                            "metadata": {
                                "sourceIP": "198.18.0.1",
                                "sourcePort": 53530,
                                "network": "udp",
                            },
                        }
                    ]
                }

        snapshots = Client().connection_snapshots(
            process_lookup_factory=lambda: events.append("lsof")
            or (lambda source_ip, port, network: "ChatGPT")
        )

        self.assertEqual(events, ["controller", "lsof"])
        self.assertEqual(snapshots[0].process, "ChatGPT")

    def test_skips_process_table_when_controller_metadata_is_complete(self):
        class Client(MihomoClient):
            def raw_connections(self):
                return {"connections": [{"id": "known", "metadata": {"process": "Cursor"}}]}

        snapshots = Client().connection_snapshots(
            process_lookup_factory=lambda: self.fail("lsof should not run")
        )

        self.assertEqual(snapshots[0].process, "Cursor")

    def test_malformed_metadata_requests_fallback_without_crashing(self):
        class Client(MihomoClient):
            def raw_connections(self):
                return {"connections": [{"id": "malformed", "metadata": "bad"}]}

        snapshots = Client().connection_snapshots(
            process_lookup_factory=lambda: (lambda source_ip, port, network: None)
        )

        self.assertEqual(snapshots[0].process, "unknown")


if __name__ == "__main__":
    unittest.main()
