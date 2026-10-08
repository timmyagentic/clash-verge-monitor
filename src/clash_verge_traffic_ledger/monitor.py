from __future__ import annotations

import sys
import copy
import math
import time
from datetime import datetime
from typing import Callable, Iterable

from .client import MihomoClient
from .models import ConnectionSnapshot, ProcessLookup, TrafficDelta
from .process_lookup import capture_process_lookup
from .store import LedgerStore


class DeltaComputer:
    def __init__(self) -> None:
        self._last: dict[str, tuple[int, int]] = {}
        self._last_process: dict[str, str] = {}

    def compute(
        self,
        snapshots: Iterable[ConnectionSnapshot],
        now: datetime,
        since: datetime | None = None,
    ) -> list[TrafficDelta]:
        deltas: list[TrafficDelta] = []
        seen: set[str] = set()

        for snapshot in snapshots:
            seen.add(snapshot.connection_id)
            process = snapshot.process
            if process != "unknown":
                self._last_process[snapshot.connection_id] = process
            else:
                process = self._last_process.get(snapshot.connection_id, process)
            previous = self._last.get(snapshot.connection_id)
            self._last[snapshot.connection_id] = (snapshot.upload, snapshot.download)
            if previous is None:
                # Only count initial bytes if core metadata proves this connection
                # was created during an uninterrupted, successfully sampled interval.
                if since is None or snapshot.started_at is None or not since <= snapshot.started_at <= now:
                    continue
                previous = (0, 0)

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
                    process=process,
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
                self._last_process.pop(connection_id, None)

        return deltas


class Sampler:
    def __init__(
        self,
        client: MihomoClient,
        store: LedgerStore,
        interval: float = 1.0,
        max_backoff: float = 30.0,
        process_lookup_factory: Callable[[], ProcessLookup] = capture_process_lookup,
    ) -> None:
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("interval must be positive")
        if not math.isfinite(max_backoff) or max_backoff < interval:
            raise ValueError("max_backoff must be at least the polling interval")
        self.client = client
        self.store = store
        self.interval = interval
        self.max_backoff = max_backoff
        self.process_lookup_factory = process_lookup_factory
        self.delta_computer = DeltaComputer()
        self.last_success = None
        self.last_identity = None
        self.last_totals = None

    def sample_once(self, now: datetime | None = None) -> int:
        timestamp = now or datetime.now().astimezone()
        started = time.monotonic()
        # Commit the baseline only after the database transaction succeeds.
        computer = copy.deepcopy(self.delta_computer)
        try:
            snapshots = self.client.connection_snapshots(
                process_lookup_factory=self.process_lookup_factory
            )
            timestamp = now or datetime.now().astimezone()
            identity = getattr(self.client, 'identity', '')
            totals = getattr(self.client, 'last_totals', None)
            elapsed = (timestamp-self.last_success).total_seconds() if self.last_success else 0
            gap = elapsed < 0 or elapsed > max(5, self.interval * 3) or (self.last_success is not None and self.last_success.utcoffset() != timestamp.utcoffset())
            reset = totals is not None and self.last_totals is not None and any(
                a < b for a,b in zip(totals,self.last_totals))
            changed = self.last_identity is not None and self.last_identity != identity
            if gap or reset or changed:
                computer = DeltaComputer()
            deltas = computer.compute(snapshots, timestamp, since=self.last_success if not (gap or reset or changed) else None)
            covered = elapsed if self.last_success and not (gap or reset or changed) else 0
            core_delta = tuple(a-b for a,b in zip(totals,self.last_totals)) if (
                covered > 0 and totals is not None and self.last_totals is not None) else None
            if hasattr(self.store, 'record_sample'):
                self.store.record_sample(timestamp, deltas, interval=self.interval,
                    covered=covered, controller=getattr(self.client,'resolved_controller',''),
                    identity=identity, connection_count=len(snapshots), duration=time.monotonic()-started,
                    core_delta=core_delta, event='baseline_reset' if gap or reset or changed else None)
            else:
                self.store.record_deltas(deltas)
        except Exception as exc:
            self.delta_computer = DeltaComputer()
            self.last_success = None
            self.last_totals = None
            if hasattr(self.store, 'record_sample'):
                self.store.record_sample(timestamp, [], interval=self.interval,
                    error=type(exc).__name__, controller=getattr(self.client,'resolved_controller',''),
                    identity=getattr(self.client,'identity',''), duration=time.monotonic()-started)
            raise
        self.delta_computer = computer
        self.last_success = timestamp
        self.last_identity = identity
        self.last_totals = totals
        return len(deltas)

    def run_forever(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        error_writer: Callable[[str], None] | None = None,
    ) -> None:
        write_error = error_writer or (lambda message: print(message, file=sys.stderr, flush=True))
        consecutive_failures = 0
        while True:
            started_at = monotonic()
            try:
                self.sample_once()
                consecutive_failures = 0
                delay = max(0.0, self.interval - (monotonic() - started_at))
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                consecutive_failures += 1
                delay = min(self.max_backoff, self.interval * (2 ** min(consecutive_failures - 1, 8)))
                write_error(
                    "sampler error: {kind}: {message}; retrying in {delay:g}s".format(
                        kind=type(exc).__name__,
                        message="sampling failed",
                        delay=delay,
                    )
                )
            sleep(delay)
