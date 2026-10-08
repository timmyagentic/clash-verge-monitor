#!/usr/bin/env python3
"""Opt-in, local-only known-size transfer through an existing Mihomo mixed port.

Never edits Clash or the production ledger. Writes a separate QA ledger.
Run with PYTHONPATH=src python scripts/verify_live_meter.py --database data/qa/live.sqlite.
"""

import argparse
from contextlib import closing
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from clash_verge_traffic_ledger.client import ControllerConfig, MihomoClient
from clash_verge_traffic_ledger.monitor import Sampler
from clash_verge_traffic_ledger.store import LedgerStore
from clash_verge_traffic_ledger.locking import writer_lock

SIZE = 1024 * 1024
CHUNK = b"x" * (64 * 1024)


def verify(database, proxy_port):
    if Path(database).exists():
        raise ValueError("Use a new QA database path")
    received = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(SIZE))
            self.end_headers()
            time.sleep(1)
            for _ in range(SIZE // len(CHUNK)):
                # Reserve the final byte so the last bulk chunk remains observable.
                block = CHUNK[:-1] if _ == SIZE // len(CHUNK) - 1 else CHUNK
                self.wfile.write(block)
                self.wfile.flush()
                time.sleep(0.1)
            time.sleep(0.5)
            self.wfile.write(b"x")
            self.wfile.flush()

        def do_POST(self):
            remaining = int(self.headers["Content-Length"])
            total = 0
            while remaining:
                data = self.rfile.read(min(len(CHUNK), remaining))
                if not data:
                    raise ConnectionError("Upload closed before declared length")
                remaining -= len(data)
                total += len(data)
            received.append(total)
            time.sleep(0.5)  # Keep the completed upload observable before replying.
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            self.wfile.flush()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stop = threading.Event()
    errors = []
    with writer_lock(database):
        store = LedgerStore(database)
        client = MihomoClient(ControllerConfig())
        sampler = Sampler(client, store, interval=0.1)

        def sample():
            while not stop.is_set():
                try:
                    sampler.sample_once()
                except Exception as e:
                    errors.append(type(e).__name__)
                stop.wait(0.1)

        worker = threading.Thread(target=sample)
        worker.start()
        c = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        port = server.server_port
        try:
            time.sleep(0.4)
            c.request("GET", f"http://127.0.0.1:{port}/download")
            response = c.getresponse()
            body = response.read()
            assert response.status == 200 and body == CHUNK * (SIZE // len(CHUNK))
            time.sleep(0.5)
            c.putrequest("POST", f"http://127.0.0.1:{port}/upload")
            c.putheader("Content-Length", str(SIZE))
            c.endheaders()
            time.sleep(1)
            for _ in range(SIZE // len(CHUNK)):
                c.send(CHUNK)
                time.sleep(0.1)
            response = c.getresponse()
            assert response.status == 200 and response.read() == b"ok"
            time.sleep(0.5)
        finally:
            c.close()
            stop.set()
            worker.join(timeout=15)
            server.shutdown()
            server.server_close()
        with closing(store.connect()) as db:
            row = db.execute(
                "SELECT coalesce(sum(upload_bytes),0),coalesce(sum(download_bytes),0) FROM traffic_deltas WHERE destination_port=?",
                (port,),
            ).fetchone()
        up, down = tuple(row)
        assert received == [SIZE], received
        assert not errors, errors
        assert SIZE * 0.98 <= up <= SIZE * 1.02, (up, SIZE)
        assert SIZE * 0.98 <= down <= SIZE * 1.02, (down, SIZE)
        return dict(
            expected_upload=SIZE,
            expected_download=SIZE,
            recorded_upload=up,
            recorded_download=down,
            upload_error_ratio=abs(up - SIZE) / SIZE,
            download_error_ratio=abs(down - SIZE) / SIZE,
            controller=client.resolved_controller,
            health=store.sampling_state()["status"],
            errors=errors,
            note="Paced loopback transfer held observable before completion. Immediate-close tails and short connections can be missed; core comparison reports the gap.",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--proxy-port", type=int, default=7897)
    args = parser.parse_args()
    print(json.dumps(verify(args.database, args.proxy_port), indent=2))
