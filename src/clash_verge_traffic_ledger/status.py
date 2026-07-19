from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .reports import human_bytes
from .service import DEFAULT_LABEL, service_state
from .store import LedgerStore

ServiceStateReader = Callable[[str], str]


@dataclass(frozen=True)
class LedgerStatus:
    database_path: str
    database_exists: bool
    service_label: str | None
    service_state: str | None
    latest_sample: str | None
    raw_delta_rows: int
    today_upload_bytes: int
    today_download_bytes: int
    today_total_bytes: int


def build_status(
    store: LedgerStore,
    date: str,
    service_label: str | None = DEFAULT_LABEL,
    service_state_reader: ServiceStateReader = service_state,
) -> LedgerStatus:
    total = store.daily_total(date)
    state = service_state_reader(service_label) if service_label else None
    return LedgerStatus(
        database_path=str(store.path),
        database_exists=store.path.exists(),
        service_label=service_label,
        service_state=state,
        latest_sample=store.latest_delta_timestamp(),
        raw_delta_rows=store.raw_delta_count(),
        today_upload_bytes=total["upload_bytes"],
        today_download_bytes=total["download_bytes"],
        today_total_bytes=total["total_bytes"],
    )


def format_status(status: LedgerStatus, date: str) -> str:
    lines = [
        "# Ledger status",
        "",
        f"Database: {status.database_path}",
        f"Database exists: {'yes' if status.database_exists else 'no'}",
        f"Service label: {status.service_label or 'not checked'}",
        f"Service state: {status.service_state or 'not checked'}",
        f"Latest sample: {status.latest_sample or 'none'}",
        f"Raw delta rows: {status.raw_delta_rows}",
        f"Date: {date}",
        f"Today upload: {human_bytes(status.today_upload_bytes)}",
        f"Today download: {human_bytes(status.today_download_bytes)}",
        f"Today total: {human_bytes(status.today_total_bytes)}",
    ]
    return "\n".join(lines)
