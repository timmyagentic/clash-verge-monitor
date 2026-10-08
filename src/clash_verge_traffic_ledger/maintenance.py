"""Explicit, non-overwriting backups/restores and configurable retention plans."""

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import os
import sqlite3
import tempfile
import tomllib

from .locking import writer_lock
from .store import LedgerStore
from .telemetry import SCHEMA_VERSION


def backup_database(source, destination):
    source, target = (
        Path(source).expanduser().resolve(),
        Path(destination).expanduser().resolve(),
    )
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError("Destination already exists; backups never overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ledger-backup-", dir=target.parent)
    os.close(fd)
    try:
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(tmp)) as dst,
        ):
            if src.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
                raise ValueError("Unsupported backup schema")
            tables = {
                r[0]
                for r in src.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"traffic_deltas", "daily_process", "daily_host"} <= tables:
                raise ValueError("Not a traffic ledger database")
            src.backup(dst)
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed")
        os.chmod(tmp, 0o600)
        os.link(tmp, target)  # Atomic publish, fails if another writer created target.
        return {"path": str(target), "bytes": target.stat().st_size, "integrity": "ok"}
    finally:
        Path(tmp).unlink(missing_ok=True)


def restore_database(source, destination, apply=False):
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(
            "Restore requires a new path; it never replaces a live database"
        )
    # Verify source without creating or changing it even in preview mode.
    store = LedgerStore(source, read_only=True)
    with closing(store.connect()) as c:
        if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
        if c.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
            raise ValueError("Unsupported backup schema")
        store.rollup_bounds()
    plan = {"source": str(store.path), "destination": str(target), "apply": apply}
    if apply:
        with writer_lock(target):
            plan["result"] = backup_database(source, target)
    return plan


def retention(store, config=None, apply=False, today=None):
    settings = {
        "raw_days": 30,
        "heartbeat_days": 90,
        "event_days": 90,
        "compact": False,
    }
    if config:
        with open(config, "rb") as f:
            supplied = tomllib.load(f).get("retention", {})
        if set(supplied) - set(settings):
            raise ValueError("Unknown retention setting")
        settings.update(supplied)
    for key in ("raw_days", "heartbeat_days", "event_days"):
        if type(settings[key]) is not int or not 1 <= settings[key] <= 3650:
            raise ValueError(f"{key} must be 1–3650")
    if type(settings["compact"]) is not bool:
        raise ValueError("compact must be a boolean")
    now = today or date.today()
    cuts = {
        key: (now - timedelta(days=settings[key])).isoformat()
        for key in ("raw_days", "heartbeat_days", "event_days")
    }
    result = {
        "apply": apply,
        "settings": settings,
        "cutoffs": cuts,
        "raw_rows": store.raw_delta_count_before(cuts["raw_days"]),
        "preserved": ["daily_process", "daily_host", "hourly_traffic"],
        "note": "Deleting heartbeats makes old coverage unknown; no automatic scheduled deletion.",
    }
    if apply:
        store._require_writable()
        result["deleted_raw_rows"] = store.delete_raw_before(cuts["raw_days"])
        with closing(store.connect()) as c:
            with c:
                c.execute(
                    "DELETE FROM sample_minutes WHERE minute<?",
                    (cuts["heartbeat_days"],),
                )
                c.execute(
                    "DELETE FROM sampler_events WHERE ts<?", (cuts["event_days"],)
                )
            if settings["compact"]:
                c.execute("VACUUM")
    return result
