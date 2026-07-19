from __future__ import annotations

import sys
import time
from datetime import datetime
from typing import Callable, Iterable

from .client import MihomoClient
from .models import ConnectionSnapshot, TrafficDelta
from .process_lookup import lookup_process_name
from .store import LedgerStore


class DeltaComputer:
    def __init__(self) -> None:
        self._last: dict[str, tuple[int, int]] = {}

    def compute(
        self,
        snapshots: Iterable[ConnectionSnapshot],
        now: datetime,
    ) -> list[TrafficDelta]:
        deltas: list[TrafficDelta] = []
        seen: set[str] = set()

        for snapshot in snapshots:
            seen.add(snapshot.connection_id)
            previous = self._last.get(snapshot.connection_id)
            self._last[snapshot.connection_id] = (snapshot.upload, snapshot.download)
            if previous is None:
                continue

            upload_delta = snapshot.upload - previous[0]
            download_delta = snapshot.download - previous[1]
            if upload_delta < 0 or download_delta < 0:
                continue
            if upload_delta == 0 and download_delta == 0:
                continue

            deltas.append(
                TrafficDelta(
                    ts=now,
                    date=now.date().isoformat(),
                    connection_id=snapshot.connection_id,
                    process=snapshot.process,
                    host=snapshot.host,
                    destination_ip=snapshot.destination_ip,
                    source_ip=snapshot.source_ip,
                    source_port=snapshot.source_port,
                    destination_port=snapshot.destination_port,
                    network=snapshot.network,
                    connection_type=snapshot.connection_type,
                    chains=snapshot.chains,
                    rule=snapshot.rule,
                    upload_bytes=upload_delta,
                    download_bytes=download_delta,
                )
            )

        for connection_id in list(self._last):
            if connection_id not in seen:
                del self._last[connection_id]

        return deltas


class Sampler:
    def __init__(
        self,
        client: MihomoClient,
        store: LedgerStore,
        interval: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if max_backoff < interval:
            raise ValueError("max_backoff must be at least the polling interval")
        self.client = client
        self.store = store
        self.interval = interval
        self.max_backoff = max_backoff
        self.delta_computer = DeltaComputer()

    def sample_once(self, now: datetime | None = None) -> int:
        timestamp = now or datetime.now().astimezone()
        snapshots = self.client.connection_snapshots(process_lookup=lookup_process_name)
        deltas = self.delta_computer.compute(snapshots, timestamp)
        self.store.record_deltas(deltas)
        return len(deltas)

    def run_forever(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        error_writer: Callable[[str], None] | None = None,
    ) -> None:
        write_error = error_writer or (lambda message: print(message, file=sys.stderr, flush=True))
        consecutive_failures = 0
        while True:
            try:
                self.sample_once()
                consecutive_failures = 0
                delay = self.interval
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                consecutive_failures += 1
                delay = min(self.max_backoff, self.interval * (2 ** min(consecutive_failures - 1, 8)))
                write_error(
                    "sampler error: {kind}: {message}; retrying in {delay:g}s".format(
                        kind=type(exc).__name__,
                        message=exc,
                        delay=delay,
                    )
                )
            sleep(delay)
