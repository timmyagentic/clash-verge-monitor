from __future__ import annotations

from contextlib import closing
from datetime import date as Date
from datetime import timedelta
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .models import TrafficDelta


from .telemetry import TelemetryStore, route_kind, SCHEMA_VERSION


class LedgerStore(TelemetryStore):
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path).expanduser()
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(f"ledger database not found: {self.path}")
        else:
            if self.path.parent:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                with closing(self.connect()) as c:
                    if c.execute('PRAGMA user_version').fetchone()[0] > SCHEMA_VERSION:
                        raise RuntimeError('Database schema is newer than this runtime')
            self._init_schema()
            self.migrate()

    def connect(self) -> sqlite3.Connection:
        if self.read_only:
            uri = f"{self.path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=30.0)
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.row_factory = sqlite3.Row
        return connection

    def _require_writable(self) -> None:
        if self.read_only:
            raise RuntimeError("ledger store is read-only")

    def _init_schema(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
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
        self._require_writable()
        rows = list(deltas)
        if not rows:
            return
        with closing(self.connect()) as connection:
            with connection:
                self._record_rows(connection, rows)

    def _record_rows(self, connection, rows):
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
                    updated_at = CASE
                        WHEN julianday(excluded.updated_at) > julianday(updated_at)
                        THEN excluded.updated_at
                        ELSE updated_at
                    END
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
                    updated_at = CASE
                        WHEN julianday(excluded.updated_at) > julianday(updated_at)
                        THEN excluded.updated_at
                        ELSE updated_at
                    END
                """,
                (delta.date, delta.host, delta.upload_bytes, delta.download_bytes, ts),
            )
            connection.execute("""INSERT INTO hourly_traffic VALUES (?,?,?,?,?,?)
                ON CONFLICT(hour,process,host,route) DO UPDATE SET
                upload_bytes=upload_bytes+excluded.upload_bytes,
                download_bytes=download_bytes+excluded.download_bytes""",
                (ts[:13], delta.process, delta.host, route_kind(delta.chains),
                 delta.upload_bytes, delta.download_bytes))

    def daily_process(self, date: str, limit: int = 20) -> list[dict[str, int | str]]:
        return self._daily_rows("daily_process", "process", date, limit)

    def daily_host(self, date: str, limit: int = 20) -> list[dict[str, int | str]]:
        return self._daily_rows("daily_host", "host", date, limit)

    def daily_total(self, date: str) -> dict[str, int]:
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(upload_bytes), 0) AS upload_bytes,
                       COALESCE(SUM(download_bytes), 0) AS download_bytes
                FROM daily_process
                WHERE date = ?
                """,
                (date,),
            ).fetchone()
        upload = int(row["upload_bytes"])
        download = int(row["download_bytes"])
        return {
            "upload_bytes": upload,
            "download_bytes": download,
            "total_bytes": upload + download,
        }

    def latest_delta_timestamp(self) -> str | None:
        with closing(self.connect()) as connection:
            # Daily rollups retain the last contributing delta timestamp even
            # after raw evidence is compacted, and are far smaller to scan.
            row = connection.execute(
                """
                SELECT updated_at AS latest
                FROM daily_process
                ORDER BY julianday(updated_at) DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row["latest"]) if row and row["latest"] else None

    def raw_delta_count(self) -> int:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM traffic_deltas").fetchone()
        return int(row["count"])

    def raw_delta_count_before(self, date: str) -> int:
        self._validate_retention_date(date)
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM traffic_deltas WHERE date < ?",
                (date,),
            ).fetchone()
        return int(row["count"])

    def delete_raw_before(self, date: str) -> int:
        self._require_writable()
        self._validate_retention_date(date)
        with closing(self.connect()) as connection:
            with connection:
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM traffic_deltas WHERE date < ?",
                    (date,),
                ).fetchone()
                connection.execute("DELETE FROM traffic_deltas WHERE date < ?", (date,))
        return int(count["count"])

    def compact_raw_before(self, date: str) -> dict[str, int]:
        self._require_writable()
        database_bytes_before = self.path.stat().st_size
        deleted = self.delete_raw_before(date)
        with closing(self.connect()) as connection:
            connection.execute("VACUUM")
        database_bytes_after = self.path.stat().st_size
        return {
            "deleted_raw_rows": deleted,
            "remaining_raw_rows": self.raw_delta_count(),
            "preserved_rollup_dates": self.rollup_date_count(),
            "database_bytes_before": database_bytes_before,
            "database_bytes_after": database_bytes_after,
            "reclaimed_bytes": max(0, database_bytes_before - database_bytes_after),
        }

    def rollup_date_count(self) -> int:
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT date FROM daily_process
                    UNION
                    SELECT date FROM daily_host
                )
                """
            ).fetchone()
        return int(row["count"])

    def daily_totals(self, end_date: str, days: int = 7) -> list[dict[str, int | str]]:
        end = Date.fromisoformat(end_date)
        start = end - timedelta(days=max(days, 1) - 1)
        totals: dict[str, dict[str, int | str]] = {}
        for offset in range((end - start).days + 1):
            current = (start + timedelta(days=offset)).isoformat()
            totals[current] = {
                "date": current,
                "upload_bytes": 0,
                "download_bytes": 0,
                "total_bytes": 0,
            }

        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT date,
                       COALESCE(SUM(upload_bytes), 0) AS upload_bytes,
                       COALESCE(SUM(download_bytes), 0) AS download_bytes
                FROM daily_process
                WHERE date BETWEEN ? AND ?
                GROUP BY date
                ORDER BY date
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        for row in rows:
            upload = int(row["upload_bytes"])
            download = int(row["download_bytes"])
            totals[str(row["date"])] = {
                "date": str(row["date"]),
                "upload_bytes": upload,
                "download_bytes": download,
                "total_bytes": upload + download,
            }
        return list(totals.values())

    def active_dates(self, start_date: str, end_date: str) -> list[str]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT date
                FROM daily_process
                WHERE date BETWEEN ? AND ?
                GROUP BY date
                HAVING SUM(upload_bytes + download_bytes) > 0
                ORDER BY date
                """,
                (start_date, end_date),
            ).fetchall()
        return [str(row["date"]) for row in rows]

    def subject_daily(
        self,
        subject_type: str,
        start_date: str,
        end_date: str,
        subject: str | None = None,
    ) -> list[dict[str, int | str]]:
        table, key = self._subject_table(subject_type)
        parameters: list[str] = [start_date, end_date]
        subject_filter = ""
        if subject is not None:
            subject_filter = f" AND {key} = ?"
            parameters.append(subject)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT date, {key} AS subject, upload_bytes, download_bytes,
                       upload_bytes + download_bytes AS total_bytes
                FROM {table}
                WHERE date BETWEEN ? AND ?{subject_filter}
                ORDER BY date, total_bytes DESC
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def evidence_breakdown(
        self,
        subject_type: str,
        subject: str,
        start_date: str,
        end_date: str,
        limit: int = 20,
    ) -> list[dict[str, int | str]]:
        _, key = self._subject_table(subject_type)
        counterpart = "host" if subject_type == "process" else "process"
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT {counterpart} AS counterpart,
                       source_ip,
                       destination_ip,
                       destination_port,
                       rule,
                       network,
                       COUNT(*) AS delta_rows,
                       COUNT(DISTINCT connection_id) AS connections,
                       MIN(ts) AS first_seen,
                       MAX(ts) AS last_seen,
                       SUM(upload_bytes) AS upload_bytes,
                       SUM(download_bytes) AS download_bytes,
                       SUM(upload_bytes + download_bytes) AS total_bytes
                FROM traffic_deltas
                WHERE date BETWEEN ? AND ? AND {key} = ?
                GROUP BY {counterpart}, source_ip, destination_ip, destination_port, rule, network
                ORDER BY total_bytes DESC
                LIMIT ?
                """,
                (start_date, end_date, subject, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def evidence_source_breakdown(
        self,
        subject_type: str,
        subject: str,
        start_date: str,
        end_date: str,
        limit: int = 20,
    ) -> list[dict[str, int | str]]:
        _, key = self._subject_table(subject_type)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT source_ip,
                       COUNT(*) AS delta_rows,
                       COUNT(DISTINCT connection_id) AS connections,
                       MIN(ts) AS first_seen,
                       MAX(ts) AS last_seen,
                       SUM(upload_bytes) AS upload_bytes,
                       SUM(download_bytes) AS download_bytes,
                       SUM(upload_bytes + download_bytes) AS total_bytes
                FROM traffic_deltas
                WHERE date BETWEEN ? AND ? AND {key} = ?
                GROUP BY source_ip
                ORDER BY total_bytes DESC
                LIMIT ?
                """,
                (start_date, end_date, subject, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def evidence_connection_pattern(
        self,
        subject_type: str,
        subject: str,
        start_date: str,
        end_date: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        _, key = self._subject_table(subject_type)
        cte = f"""
            WITH connection_totals AS (
                SELECT connection_id,
                       source_ip,
                       MIN(ts) AS first_seen,
                       MAX(ts) AS last_seen,
                       SUM(upload_bytes) AS upload_bytes,
                       SUM(download_bytes) AS download_bytes,
                       SUM(upload_bytes + download_bytes) AS total_bytes
                FROM traffic_deltas
                WHERE date BETWEEN ? AND ? AND {key} = ?
                GROUP BY connection_id, source_ip
            )
        """
        parameters = (start_date, end_date, subject)
        with closing(self.connect()) as connection:
            summary = connection.execute(
                cte
                + """
                SELECT COUNT(*) AS connection_count,
                       COALESCE(MIN(total_bytes), 0) AS min_connection_bytes,
                       COALESCE(AVG(total_bytes), 0) AS average_connection_bytes,
                       COALESCE(MAX(total_bytes), 0) AS max_connection_bytes
                FROM connection_totals
                """,
                parameters,
            ).fetchone()
            top_rows = connection.execute(
                cte
                + """
                SELECT connection_id, source_ip, first_seen, last_seen,
                       upload_bytes, download_bytes, total_bytes
                FROM connection_totals
                ORDER BY total_bytes DESC, connection_id
                LIMIT ?
                """,
                (*parameters, limit),
            ).fetchall()
            minute_rows = connection.execute(
                cte
                + """
                SELECT CAST(strftime('%M', first_seen) AS INTEGER) AS start_minute,
                       COUNT(*) AS connection_count
                FROM connection_totals
                GROUP BY start_minute
                ORDER BY connection_count DESC, start_minute
                """,
                parameters,
            ).fetchall()
            source_minute_rows = connection.execute(
                cte
                + """
                SELECT source_ip,
                       CAST(strftime('%M', first_seen) AS INTEGER) AS start_minute,
                       COUNT(*) AS connection_count
                FROM connection_totals
                GROUP BY source_ip, start_minute
                ORDER BY source_ip, connection_count DESC, start_minute
                """,
                parameters,
            ).fetchall()

        connection_count = int(summary["connection_count"])
        dominant_minute = int(minute_rows[0]["start_minute"]) if minute_rows else None
        dominant_count = int(minute_rows[0]["connection_count"]) if minute_rows else 0
        dominant_ratio = dominant_count / connection_count if connection_count else 0.0
        source_distributions: dict[str, list[dict[str, int | str]]] = {}
        for row in source_minute_rows:
            source_distributions.setdefault(str(row["source_ip"]), []).append(dict(row))
        periodic_clusters: list[dict[str, Any]] = []
        for source_ip, distribution in source_distributions.items():
            source_count = sum(int(item["connection_count"]) for item in distribution)
            source_dominant = distribution[0]
            source_dominant_count = int(source_dominant["connection_count"])
            source_ratio = source_dominant_count / source_count if source_count else 0.0
            if source_count >= 3 and source_ratio >= 0.75:
                periodic_clusters.append(
                    {
                        "source_ip": source_ip,
                        "connection_count": source_count,
                        "dominant_start_minute": int(source_dominant["start_minute"]),
                        "dominant_start_count": source_dominant_count,
                        "dominant_start_ratio": round(source_ratio, 6),
                    }
                )
        periodic_clusters.sort(
            key=lambda item: (-int(item["dominant_start_count"]), str(item["source_ip"]))
        )
        return {
            "connection_count": connection_count,
            "min_connection_bytes": int(summary["min_connection_bytes"]),
            "average_connection_bytes": round(float(summary["average_connection_bytes"]), 3),
            "max_connection_bytes": int(summary["max_connection_bytes"]),
            "top_connections": [dict(row) for row in top_rows],
            "start_minute_distribution": [dict(row) for row in minute_rows],
            "dominant_start_minute": dominant_minute,
            "dominant_start_count": dominant_count,
            "dominant_start_ratio": round(dominant_ratio, 6),
            "periodic_start_pattern": bool(
                (connection_count >= 3 and dominant_ratio >= 0.75) or periodic_clusters
            ),
            "periodic_clusters": periodic_clusters,
        }

    def rollup_bounds(self) -> dict[str, str | None]:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT MIN(date) AS first_date, MAX(date) AS last_date FROM daily_process"
            ).fetchone()
        return {
            "first_date": str(row["first_date"]) if row["first_date"] else None,
            "last_date": str(row["last_date"]) if row["last_date"] else None,
        }

    def raw_bounds(self) -> dict[str, str | None]:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT MIN(date) AS first_date, MAX(date) AS last_date FROM traffic_deltas"
            ).fetchone()
        return {
            "first_date": str(row["first_date"]) if row["first_date"] else None,
            "last_date": str(row["last_date"]) if row["last_date"] else None,
        }

    @staticmethod
    def _validate_retention_date(value: str) -> None:
        try:
            normalized = Date.fromisoformat(value).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("retention cutoff must use YYYY-MM-DD") from exc
        if normalized != value:
            raise ValueError("retention cutoff must use YYYY-MM-DD")

    @staticmethod
    def _subject_table(subject_type: str) -> tuple[str, str]:
        if subject_type == "process":
            return "daily_process", "process"
        if subject_type == "host":
            return "daily_host", "host"
        raise ValueError(f"unsupported subject type: {subject_type}")

    def _daily_rows(
        self,
        table: str,
        key: str,
        date: str,
        limit: int,
    ) -> list[dict[str, int | str]]:
        with closing(self.connect()) as connection:
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
