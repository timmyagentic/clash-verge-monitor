import subprocess
import unittest

from clash_verge_traffic_ledger.process_lookup import (
    capture_process_table,
    choose_process_name,
    parse_lsof_process_names,
    parse_lsof_socket_owners,
)


class ProcessLookupTests(unittest.TestCase):
    def test_parses_lsof_field_output(self):
        output = "p123\ncverge-mihomo-alpha\np456\ncCursor\n"

        self.assertEqual(parse_lsof_process_names(output), ["verge-mihomo-alpha", "Cursor"])
        self.assertEqual(choose_process_name(["verge-mihomo-alpha", "Cursor"]), "Cursor")

    def test_does_not_attribute_traffic_to_the_proxy_core(self):
        self.assertIsNone(choose_process_name(["verge-mihomo-alpha"]))
        self.assertIsNone(choose_process_name([]))

    def test_parses_tcp_udp_and_ipv6_local_endpoints(self):
        output = "\n".join(
            [
                "p123",
                "cChatGPT",
                "f7",
                "PTCP",
                "n127.0.0.1:65087->104.18.1.1:443",
                "f8",
                "PUDP",
                "n[::1]:53530->[2001:4860:4860::8888]:443",
                "p456",
                "cverge-mihomo-alpha",
                "f9",
                "PTCP",
                "n*:65087",
            ]
        )

        owners = parse_lsof_socket_owners(output)

        self.assertEqual(
            [(item.process, item.protocol, item.local_address, item.local_port) for item in owners],
            [
                ("ChatGPT", "tcp", "127.0.0.1", 65087),
                ("ChatGPT", "udp", "::1", 53530),
                ("verge-mihomo-alpha", "tcp", "*", 65087),
            ],
        )

    def test_captures_lsof_once_and_resolves_tun_by_protocol_and_port(self):
        calls = []
        output = "\n".join(
            [
                "p123",
                "cChatGPT",
                "f7",
                "PTCP",
                "n127.0.0.1:65087->104.18.1.1:443",
                "p456",
                "cnode",
                "f8",
                "PUDP",
                "n*:53530",
                "p789",
                "cverge-mihomo-alpha",
                "f9",
                "PTCP",
                "n*:65087",
            ]
        )

        def runner(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")

        table = capture_process_table(runner=runner)

        self.assertEqual(table.lookup("198.18.0.1", 65087, "tcp"), "ChatGPT")
        self.assertEqual(table.lookup("198.18.0.1", 53530, "udp"), "node")
        self.assertIsNone(table.lookup("198.18.0.1", 53530, "tcp"))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
