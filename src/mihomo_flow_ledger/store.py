from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import TrafficDelta


class LedgerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.parent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS traffic_deltas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    date TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    process TEXT NOT NULL,
                    host TEXT NOT NULL,
                    destination_ip TEXT NOT NULL,
                    source_ip TEXT NOT NULL,
                    source_port INTEGER NOT NULL,
                    destination_port INTEGER NOT NULL,
                    network TEXT NOT NULL,
                    connection_type TEXT NOT NULL,
                    chains_json TEXT NOT NULL,
                    rule TEXT NOT NULL,
                    upload_bytes INTEGER NOT NULL,
                    download_bytes INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_traffic_deltas_date_process
                ON traffic_deltas(date, process);

                CREATE INDEX IF NOT EXISTS idx_traffic_deltas_date_host
                ON traffic_deltas(date, host);

                CREATE TABLE IF NOT EXISTS daily_process (
                    date TEXT NOT NULL,
                    process TEXT NOT NULL,
                    upload_bytes INTEGER NOT NULL DEFAULT 0,
                    download_bytes INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (date, process)
                );

                CREATE TABLE IF NOT EXISTS daily_host (
                    date TEXT NOT NULL,
                    host TEXT NOT NULL,
                    upload_bytes INTEGER NOT NULL DEFAULT 0,
                    download_bytes INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (date, host)
                );
                """
            )

    def record_deltas(self, deltas: Iterable[TrafficDelta]) -> None:
        rows = list(deltas)
        if not rows:
            return
        with self.connect() as connection:
            for delta in rows:
                ts = delta.ts.isoformat()
                connection.execute(
                    """
                    INSERT INTO traffic_deltas (
                        ts, date, connection_id, process, host, destination_ip, source_ip,
                        source_port, destination_port, network, connection_type, chains_json,
                        rule, upload_bytes, download_bytes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        delta.date,
                        delta.connection_id,
                        delta.process,
                        delta.host,
                        delta.destination_ip,
                        delta.source_ip,
                        delta.source_port,
                        delta.destination_port,
                        delta.network,
                        delta.connection_type,
                        json.dumps(delta.chains),
                        delta.rule,
                        delta.upload_bytes,
                        delta.download_bytes,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO daily_process (date, process, upload_bytes, download_bytes, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(date, process) DO UPDATE SET
                        upload_bytes = upload_bytes + excluded.upload_bytes,
                        download_bytes = download_bytes + excluded.download_bytes,
                        updated_at = excluded.updated_at
                    """,
                    (delta.date, delta.process, delta.upload_bytes, delta.download_bytes, ts),
                )
                connection.execute(
                    """
                    INSERT INTO daily_host (date, host, upload_bytes, download_bytes, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(date, host) DO UPDATE SET
                        upload_bytes = upload_bytes + excluded.upload_bytes,
                        download_bytes = download_bytes + excluded.download_bytes,
                        updated_at = excluded.updated_at
                    """,
                    (delta.date, delta.host, delta.upload_bytes, delta.download_bytes, ts),
                )

    def daily_process(self, date: str, limit: int = 20) -> list[dict[str, int | str]]:
        return self._daily_rows("daily_process", "process", date, limit)

    def daily_host(self, date: str, limit: int = 20) -> list[dict[str, int | str]]:
        return self._daily_rows("daily_host", "host", date, limit)

    def _daily_rows(
        self,
        table: str,
        key: str,
        date: str,
        limit: int,
    ) -> list[dict[str, int | str]]:
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {key}, upload_bytes, download_bytes,
                       upload_bytes + download_bytes AS total_bytes
                FROM {table}
                WHERE date = ?
                ORDER BY total_bytes DESC
                LIMIT ?
                """,
                (date, limit),
            ).fetchall()
        return [dict(row) for row in rows]

