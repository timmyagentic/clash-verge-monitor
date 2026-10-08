"""Exercise real Unix HTTP, endpoint migration and browser-facing HTTP boundaries."""

from http.server import BaseHTTPRequestHandler
import http.client
import json
import multiprocessing
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from clash_verge_traffic_ledger.client import ControllerConfig, MihomoClient
from clash_verge_traffic_ledger.store import LedgerStore
from clash_verge_traffic_ledger.web import serve_dashboard
from clash_verge_traffic_ledger.agent_api import query_response


class UnixControllerTests(unittest.TestCase):
    def test_real_socket_disappearance_and_recovery(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"version": "test"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory(prefix="ldg-", dir="/tmp") as tmp:
            paths = [str(Path(tmp) / "a.sock"), str(Path(tmp) / "b.sock")]
            server = socketserver.UnixStreamServer(paths[0], Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            client = MihomoClient(ControllerConfig("auto", timeout=0.2))
            with patch(
                "clash_verge_traffic_ledger.client.controller_candidates",
                return_value=paths,
            ):
                self.assertEqual(client.version()["version"], "test")
                server.shutdown()
                server.server_close()
                worker.join()
                Path(paths[0]).unlink()
                with self.assertRaises(ConnectionError):
                    client.version()
                server = socketserver.UnixStreamServer(paths[1], Handler)
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    self.assertEqual(client.version()["version"], "test")
                    self.assertEqual(client.resolved_controller, paths[1])
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join()


class DashboardHTTPTests(unittest.TestCase):
    def test_http_filter_export_validation_and_read_only_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite"
            LedgerStore(path)
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            proc = multiprocessing.Process(
                target=serve_dashboard,
                args=(LedgerStore(path, read_only=True), "127.0.0.1", port),
            )
            proc.start()
            try:
                for _ in range(100):
                    try:
                        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                        conn.request("GET", "/?date=2026-10-08")
                        r = conn.getresponse()
                        body = r.read()
                        break
                    except OSError:
                        time.sleep(0.02)
                else:
                    self.fail("Server did not start")
                self.assertEqual(r.status, 200)
                self.assertIn("覆盖未知".encode(), body)
                self.assertIn("frame-ancestors", r.getheader("Content-Security-Policy"))
                for url, headers, expected in [
                    ("/?start=invalid", {}, 400),
                    ("/assets/dashboard.css", {}, 200),
                    ("/assets/dashboard.js", {}, 200),
                    ("/assets/icons/world.svg", {}, 200),
                    ("/assets/../../pyproject.toml", {}, 404),
                    ("/?start=2020-01-01&end=2026-10-08", {}, 400),
                    ("/", {"Host": "evil.test"}, 403),
                    ("/", {"Origin": "http://evil.test"}, 403),
                    ("/api/explore?start=2026-10-08&end=2026-10-08&by=route", {}, 200),
                    ("/export.csv?start=2026-10-08&end=2026-10-08", {}, 200),
                ]:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                    conn.request("GET", url, headers=headers)
                    r = conn.getresponse()
                    r.read()
                    conn.close()
                    self.assertEqual(r.status, expected, url)
                for url, operation, status in [
                    ('/api/capabilities', 'capabilities', 200),
                    ('/api/explore?start=2026-08-22&end=2026-08-22&process=App&offset=1&limit=2', 'explore', 200),
                    ('/api/audit?end=2026-08-22', 'audit', 200),
                    ('/api/evidence?case_id=invalid', 'evidence', 400),
                    ('/api/explore?start=invalid', 'explore', 400),
                    ('/api/explore?limit=1001', 'explore', 400),
                    ('/api/no-such-operation', 'no-such-operation', 404),
                ]:
                    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                    conn.request('GET', url)
                    r = conn.getresponse()
                    doc = json.loads(r.read())
                    self.assertEqual(r.status, status)
                    self.assertIn('application/json', r.getheader('Content-Type'))
                    self.assertEqual(doc['schema_version'], '1')
                    self.assertEqual(doc['operation'], operation)
                    self.assertIn('runtime', doc)
                    self.assertEqual(doc['ok'], status == 200)
                    if operation == 'explore' and status == 200:
                        expected = query_response('explore', LedgerStore(path, read_only=True),
                            start='2026-08-22', end='2026-08-22', process='App', offset=1, limit=2)
                        for key in ['data', 'query', 'warnings', 'errors']:
                            self.assertEqual(doc[key], expected[key])
                    conn.close()
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("POST", "/")
                r = conn.getresponse()
                r.read()
                conn.close()
                self.assertEqual(r.status, 501)
                self.assertEqual(LedgerStore(path, read_only=True).raw_delta_count(), 0)
            finally:
                proc.terminate()
                proc.join(timeout=5)
