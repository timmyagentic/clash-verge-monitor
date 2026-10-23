from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from typing import Any, Callable


ProcessLookup = Callable[[str, int, str], str | None]


def _to_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _basename(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        return ""
    return PurePath(normalized).name or normalized


@dataclass(frozen=True)
class ConnectionSnapshot:
    connection_id: str
    upload: int
    download: int
    process: str
    host: str
    destination_ip: str
    source_ip: str
    source_port: int
    destination_port: int
    network: str
    connection_type: str
    chains: list[str]
    rule: str
    started_at: datetime | None = None

    @classmethod
    def from_api_item(
        cls,
        item: dict[str, Any],
        process_lookup: ProcessLookup | None = None,
    ) -> "ConnectionSnapshot":
        raw_metadata = item.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        source_ip = str(metadata.get("sourceIP") or "")
        source_port = _to_int(metadata.get("sourcePort"))
        destination_ip = str(metadata.get("destinationIP") or "")
        destination_port = _to_int(metadata.get("destinationPort"))

        process = str(metadata.get("process") or "").strip()
        if process.lower() == "unknown":
            process = ""
        if not process:
            process = _basename(str(metadata.get("processPath") or ""))
        network = str(metadata.get("network") or "").strip().lower()
        lookup_network = network or "tcp"
        if not process and process_lookup and source_port and lookup_network in {"tcp", "udp"}:
            process = (process_lookup(source_ip, source_port, lookup_network) or "").strip()
        if not process:
            process = "unknown"

        host = str(metadata.get("host") or destination_ip or "unknown").strip() or "unknown"
        chains = item.get("chains") if isinstance(item.get("chains"), list) else []

        try:
            started_at = datetime.fromisoformat(str(item.get('start','')).replace('Z','+00:00'))
            if started_at.tzinfo is None:
                started_at = None
        except ValueError:
            started_at = None
        fallback_id = f"{source_ip}:{source_port}->{destination_ip}:{destination_port}"
        return cls(
            connection_id=str(item.get("id") or fallback_id),
            upload=_to_int(item.get("upload")),
            download=_to_int(item.get("download")),
            process=process,
            host=host,
            destination_ip=destination_ip,
            source_ip=source_ip,
            source_port=source_port,
            destination_port=destination_port,
            network=network,
            connection_type=str(metadata.get("type") or ""),
            chains=[str(chain) for chain in chains],
            rule=str(item.get("rule") or item.get("rulePayload") or ""),
            started_at=started_at,
        )


@dataclass(frozen=True)
class TrafficDelta:
    ts: datetime
    date: str
    connection_id: str
    process: str
    host: str
    destination_ip: str
    source_ip: str
    source_port: int
    destination_port: int
    network: str
    connection_type: str
    chains: list[str]
    rule: str
    upload_bytes: int
    download_bytes: int
