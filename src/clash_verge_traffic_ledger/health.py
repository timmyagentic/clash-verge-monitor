from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .client import ControllerConfig, MihomoClient
from .contracts import action_item, warning_item
from .service import DEFAULT_LABEL, service_state
from .store import LedgerStore


ControllerProbe = Callable[[ControllerConfig], dict[str, Any]]
ServiceStateReader = Callable[[str], str]


def probe_controller(config: ControllerConfig) -> dict[str, Any]:
    client = MihomoClient(config)
    version = client.version()
    connections = client.raw_connections().get("connections") or []
    return {
        "reachable": True,
        "version": version,
        "connection_count": len(connections),
    }


def _sample_age(latest_sample: str | None, now: datetime) -> float | None:
    if not latest_sample:
        return None
    sampled_at = datetime.fromisoformat(latest_sample)
    if sampled_at.tzinfo is None:
        sampled_at = sampled_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now.astimezone(timezone.utc) - sampled_at.astimezone(timezone.utc)).total_seconds())


def inspect_health(
    database: str | Path,
    controller: ControllerConfig,
    *,
    service_label: str | None = DEFAULT_LABEL,
    max_sample_age_seconds: float = 180.0,
    now: datetime | None = None,
    controller_probe: ControllerProbe = probe_controller,
    service_state_reader: ServiceStateReader = service_state,
    check_controller: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    timestamp = now or datetime.now(timezone.utc)
    path = Path(database).expanduser().resolve()
    warnings: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []

    database_data: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "readable": False,
        "latest_sample": None,
        "sample_age_seconds": None,
        "fresh": False,
        "rollup_bounds": {"first_date": None, "last_date": None},
    }
    if path.is_file():
        try:
            store = LedgerStore(path, read_only=True)
            latest_sample = store.latest_delta_timestamp()
            age = _sample_age(latest_sample, timestamp)
            database_data.update(
                {
                    "readable": True,
                    "latest_sample": latest_sample,
                    "sample_age_seconds": round(age, 3) if age is not None else None,
                    "fresh": age is not None and age <= max_sample_age_seconds,
                    "rollup_bounds": store.rollup_bounds(),
                }
            )
        except Exception as exc:
            database_data["error"] = f"{type(exc).__name__}: {exc}"
            warnings.append(warning_item("database_unreadable", "The ledger database could not be read."))
            next_actions.append(action_item("inspect_database", "Check the ledger path and SQLite integrity."))
    else:
        warnings.append(warning_item("database_missing", "No ledger database exists at the configured path."))
        next_actions.append(action_item("install_sampler", "Install or start the traffic sampler."))

    sampler_data: dict[str, Any] = {"checked": service_label is not None, "label": service_label, "state": None}
    if service_label:
        state = service_state_reader(service_label)
        sampler_data["state"] = state
        if state != "running":
            warnings.append(
                warning_item("sampler_not_running", "The launchd sampler is not running.", state=state)
            )
            next_actions.append(action_item("inspect_sampler", "Inspect the sampler service and error log."))

    controller_data: dict[str, Any] = {
        "checked": check_controller,
        "target": controller.controller,
        "reachable": None,
    }
    if check_controller:
        try:
            controller_data.update(controller_probe(controller))
        except Exception as exc:
            controller_data.update(
                {
                    "reachable": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            warnings.append(
                warning_item("controller_unreachable", "The Clash Verge/Mihomo controller is unreachable.")
            )
            next_actions.append(action_item("start_clash_verge", "Start Clash Verge and retry the health check."))

    if database_data["readable"] and not database_data["fresh"]:
        warnings.append(
            warning_item(
                "sample_stale",
                "The ledger is readable but its latest sample is stale.",
                max_sample_age_seconds=max_sample_age_seconds,
            )
        )

    audit_ready = bool(database_data["readable"] and database_data["rollup_bounds"]["last_date"])
    service_ready = not service_label or sampler_data["state"] == "running"
    controller_ready = not check_controller or controller_data["reachable"] is True
    sampling_ready = bool(database_data["fresh"] and service_ready and controller_ready)
    if sampling_ready:
        status = "healthy"
    elif audit_ready:
        status = "degraded"
    else:
        status = "unavailable"

    return (
        {
            "status": status,
            "audit_ready": audit_ready,
            "sampling_ready": sampling_ready,
            "database": database_data,
            "sampler": sampler_data,
            "controller": controller_data,
        },
        warnings,
        next_actions,
    )
