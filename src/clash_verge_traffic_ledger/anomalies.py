from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from datetime import timedelta

from .reports import human_bytes
from .store import LedgerStore


@dataclass(frozen=True)
class Anomaly:
    code: str
    severity: str
    message: str


def _previous_date(date: str) -> str:
    return (Date.fromisoformat(date) - timedelta(days=1)).isoformat()


def detect_anomalies(
    store: LedgerStore,
    date: str,
    byte_threshold: int,
    unknown_ratio_threshold: float,
    spike_multiplier: float,
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    processes = store.daily_process(date, limit=1000)
    hosts = store.daily_host(date, limit=1000)
    total = store.daily_total(date)["total_bytes"]

    for row in processes:
        total_bytes = int(row["total_bytes"])
        if total_bytes >= byte_threshold:
            anomalies.append(
                Anomaly(
                    code="high_process_usage",
                    severity="warning",
                    message=f"{row['process']} used {human_bytes(total_bytes)} today",
                )
            )

    for row in hosts:
        total_bytes = int(row["total_bytes"])
        if total_bytes >= byte_threshold:
            anomalies.append(
                Anomaly(
                    code="high_host_usage",
                    severity="warning",
                    message=f"{row['host']} used {human_bytes(total_bytes)} today",
                )
            )

    unknown_total = sum(
        int(row["total_bytes"]) for row in processes if str(row["process"]).lower() == "unknown"
    )
    if total and unknown_total / total >= unknown_ratio_threshold:
        percent = unknown_total / total * 100
        anomalies.append(
            Anomaly(
                code="unknown_process_ratio",
                severity="warning",
                message=f"unknown process traffic is {percent:.1f}% of today's total",
            )
        )

    previous_processes = {
        str(row["process"]): int(row["total_bytes"])
        for row in store.daily_process(_previous_date(date), limit=1000)
    }
    for row in processes:
        process = str(row["process"])
        current = int(row["total_bytes"])
        previous = previous_processes.get(process, 0)
        if previous > 0 and current >= byte_threshold and current >= previous * spike_multiplier:
            anomalies.append(
                Anomaly(
                    code="process_spike",
                    severity="warning",
                    message=(
                        f"{process} traffic jumped from {human_bytes(previous)} "
                        f"to {human_bytes(current)}"
                    ),
                )
            )

    return anomalies


def format_anomalies(anomalies: list[Anomaly], date: str) -> str:
    lines = [f"# Traffic anomalies", "", f"Date: {date}", ""]
    if not anomalies:
        lines.append("(no anomalies)")
        return "\n".join(lines)
    for anomaly in anomalies:
        lines.append(f"- [{anomaly.severity}] {anomaly.code}: {anomaly.message}")
    return "\n".join(lines)
