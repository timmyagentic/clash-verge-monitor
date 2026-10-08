"""Schema v2: bounded minute heartbeats and durable hourly traffic aggregates.

Legacy traffic is retained; a migration cannot fabricate historical coverage.
All query methods support pre-v2 databases without migrating them.
"""

from contextlib import closing
from datetime import date, datetime, timedelta

SCHEMA_VERSION = 2
ROUTE_SQL = """CASE WHEN json_extract(chains_json,'$[0]')='DIRECT' THEN 'direct'
 WHEN json_array_length(chains_json)=0 OR json_extract(chains_json,'$[0]') IN ('REJECT','REJECT-DROP')
 THEN 'unknown' ELSE 'proxy' END"""


def route_kind(chains):
    if not chains or chains[0] in ("REJECT", "REJECT-DROP"):
        return "unknown"
    return "direct" if chains[0] == "DIRECT" else "proxy"


class TelemetryStore:
    def migrate(self):
        with closing(self.connect()) as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("Database schema is newer than this runtime")
            if version == SCHEMA_VERSION:
                return
            with c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("""CREATE TABLE IF NOT EXISTS sampler_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), last_attempt TEXT, last_success TEXT,
                    status TEXT, error TEXT, controller TEXT, identity TEXT, interval REAL,
                    connection_count INTEGER, duration REAL)""")
                c.execute("""CREATE TABLE IF NOT EXISTS sample_minutes (
                    minute TEXT PRIMARY KEY, covered_seconds REAL NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
                    core_upload INTEGER NOT NULL DEFAULT 0, core_download INTEGER NOT NULL DEFAULT 0,
                    recorded_upload INTEGER NOT NULL DEFAULT 0, recorded_download INTEGER NOT NULL DEFAULT 0,
                    compared_samples INTEGER NOT NULL DEFAULT 0)""")
                c.execute("""CREATE TABLE IF NOT EXISTS sampler_events (
                    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)""")
                c.execute("""CREATE TABLE IF NOT EXISTS hourly_traffic (
                    hour TEXT, process TEXT, host TEXT, route TEXT,
                    upload_bytes INTEGER NOT NULL, download_bytes INTEGER NOT NULL,
                    PRIMARY KEY(hour,process,host,route))""")
                c.execute(f"""INSERT OR IGNORE INTO hourly_traffic
                    SELECT substr(ts,1,13),process,host,{ROUTE_SQL},sum(upload_bytes),sum(download_bytes)
                    FROM traffic_deltas GROUP BY substr(ts,1,13),process,host,{ROUTE_SQL}""")
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_delta_date_ts ON traffic_deltas(date,ts)"
                )
                c.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def has_table(self, name):
        with closing(self.connect()) as c:
            return (
                c.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
                ).fetchone()
                is not None
            )

    def sampling_state(self):
        if not self.has_table("sampler_state"):
            return {}
        with closing(self.connect()) as c:
            row = c.execute("SELECT * FROM sampler_state WHERE id=1").fetchone()
            return dict(row) if row else {}

    def record_sample(
        self,
        now,
        deltas,
        *,
        interval,
        covered=0,
        error=None,
        controller="",
        identity="",
        connection_count=0,
        duration=0,
        core_delta=None,
        event=None,
    ):
        self._require_writable()
        rows = list(deltas)
        ts = now.isoformat()
        minute = now.strftime("%Y-%m-%dT%H:%M")
        with closing(self.connect()) as c:
            with c:
                self._record_rows(c, rows)
                previous = c.execute(
                    "SELECT status,identity FROM sampler_state WHERE id=1"
                ).fetchone()
                status = "error" if error else "ok"
                c.execute(
                    """INSERT INTO sampler_state VALUES (1,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET last_attempt=excluded.last_attempt,
                    last_success=coalesce(excluded.last_success,last_success),status=excluded.status,
                    error=excluded.error,controller=excluded.controller,identity=excluded.identity,
                    interval=excluded.interval,connection_count=excluded.connection_count,duration=excluded.duration""",
                    (
                        ts,
                        None if error else ts,
                        status,
                        error,
                        controller,
                        identity,
                        interval,
                        connection_count,
                        duration,
                    ),
                )
                # Store successful interval portions on both sides of minute/day boundaries.
                remaining = max(0, covered)
                cursor = now - timedelta(seconds=remaining)
                while remaining > 0.000001:
                    end = min(
                        now,
                        cursor.replace(second=0, microsecond=0) + timedelta(minutes=1),
                    )
                    part = (end - cursor).total_seconds()
                    c.execute(
                        """INSERT INTO sample_minutes(minute,covered_seconds) VALUES (?,?)
                        ON CONFLICT(minute) DO UPDATE SET covered_seconds=min(60,covered_seconds+excluded.covered_seconds)""",
                        (cursor.strftime("%Y-%m-%dT%H:%M"), part),
                    )
                    remaining -= part
                    cursor = end
                measured = core_delta is not None
                c.execute(
                    """INSERT INTO sample_minutes(minute,successes,failures,core_upload,core_download,
                    recorded_upload,recorded_download,compared_samples) VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(minute) DO UPDATE SET successes=successes+excluded.successes,
                    failures=failures+excluded.failures,core_upload=core_upload+excluded.core_upload,
                    core_download=core_download+excluded.core_download,
                    recorded_upload=recorded_upload+excluded.recorded_upload,
                    recorded_download=recorded_download+excluded.recorded_download,
                    compared_samples=compared_samples+excluded.compared_samples""",
                    (
                        minute,
                        int(not error),
                        int(bool(error)),
                        *(core_delta or (0, 0)),
                        sum(x.upload_bytes for x in rows) if measured else 0,
                        sum(x.download_bytes for x in rows) if measured else 0,
                        int(measured),
                    ),
                )
                if (
                    previous is None
                    or previous["status"] != status
                    or previous["identity"] != identity
                    or event
                ):
                    c.execute(
                        "INSERT INTO sampler_events(ts,kind,detail) VALUES (?,?,?)",
                        (
                            ts,
                            event or ("disconnected" if error else "connected"),
                            error or identity,
                        ),
                    )

    def coverage(self, start, end, now=None):
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first > last or (last - first).days > 366:
            raise ValueError("Coverage range must be 1–367 days")
        timestamp = now or datetime.now().astimezone()
        minute_rows = []
        if self.has_table("sample_minutes"):
            with closing(self.connect()) as c:
                minute_rows = c.execute(
                    """SELECT substr(minute,1,10) day,sum(covered_seconds) covered,
                    sum(successes) successes,sum(failures) failures FROM sample_minutes
                    WHERE minute>=? AND minute<? GROUP BY day""",
                    (start, (last + timedelta(days=1)).isoformat()),
                ).fetchall()
        lookup = {r["day"]: dict(r) for r in minute_rows}
        days = []
        for i in range((last - first).days + 1):
            day = first + timedelta(days=i)
            row = lookup.get(day.isoformat(), {})
            expected = 86400.0
            if day == timestamp.date():
                expected = (
                    timestamp
                    - timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                ).total_seconds()
            if day > timestamp.date():
                expected = 0
            covered = min(expected, row.get("covered", 0))
            status = (
                "unknown"
                if not row
                else (
                    "complete" if expected and covered / expected >= 0.99 else "partial"
                )
            )
            if day >= timestamp.date() and status == "complete":
                status = "partial"
            days.append(
                {
                    "date": day.isoformat(),
                    "status": status,
                    "covered_seconds": round(covered, 3),
                    "expected_seconds": expected,
                    "ratio": round(covered / expected, 6) if expected and row else None,
                    "successes": row.get("successes", 0),
                    "failures": row.get("failures", 0),
                }
            )
        total = sum(d["covered_seconds"] for d in days)
        expected = sum(d["expected_seconds"] for d in days)
        return {
            "status": "complete"
            if all(d["status"] == "complete" for d in days)
            else (
                "unknown" if all(d["status"] == "unknown" for d in days) else "partial"
            ),
            "covered_seconds": round(total, 3),
            "expected_seconds": expected,
            "ratio": round(total / expected, 6) if minute_rows and expected else None,
            "days": days,
            "definition": "Successful bounded sample intervals; no heartbeat means unknown, not zero traffic.",
        }

    def recent_events(self, limit=30):
        if not self.has_table("sampler_events"):
            return []
        with closing(self.connect()) as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT ts,kind,detail FROM sampler_events ORDER BY id DESC LIMIT ?",
                    (min(100, limit),),
                )
            ]

    def meter_comparison(self, start, end):
        if not self.has_table("sample_minutes"):
            return {"status": "unknown"}
        with closing(self.connect()) as c:
            r = c.execute(
                """SELECT sum(compared_samples) samples,sum(core_upload) core_upload,
                sum(core_download) core_download,sum(recorded_upload) recorded_upload,
                sum(recorded_download) recorded_download FROM sample_minutes WHERE minute>=? AND minute<?""",
                (start, (date.fromisoformat(end) + timedelta(days=1)).isoformat()),
            ).fetchone()
        result = {k: (v or 0) for k, v in dict(r).items()}
        result["status"] = "available" if result["samples"] else "unknown"
        result["unattributed_bytes"] = max(
            0,
            result["core_upload"]
            + result["core_download"]
            - result["recorded_upload"]
            - result["recorded_download"],
        )
        result["note"] = (
            "Core counters versus connection deltas for comparable intervals only; not provider billing."
        )
        return result
