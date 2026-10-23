"""Shared read-only machine interface for CLI and HTTP consumers."""

from contextlib import closing
from datetime import datetime
import hashlib
from typing import Any

from .audit import POLICY_VERSION, audit_traffic, build_evidence, find_case
from .contracts import envelope, warning_item
from .explore import explore
from .store import LedgerStore
from .telemetry import SCHEMA_VERSION as DATABASE_SCHEMA_VERSION


READ_COMMANDS = ["capabilities", "health", "audit", "evidence", "explore"]


def capabilities() -> dict[str, Any]:
    return envelope(
        "capabilities",
        {
            "commands": READ_COMMANDS + ["maintenance", "backup", "restore", "retention", "migrate"],
            "read_only_commands": READ_COMMANDS,
            "database_schema_version": DATABASE_SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "groupings": ["process", "host", "route", "hour", "minute", "connection", "rule", "chain"],
            "sorts": ["total", "upload", "download", "time"],
            "limits": {"explore_max_rows": 1000, "max_range_days": 367},
            "coverage_states": ["complete", "partial", "unknown"],
            "data_states": ["unobserved", "indeterminate_zero", "observed_zero", "observed_nonzero"],
            "http_endpoints": ["/api/capabilities", "/api/explore", "/api/audit", "/api/evidence"],
            "pagination": "limit/offset; new requests read live data, not a stable pagination snapshot",
            "date_semantics": "Inclusive dates in the recorded local calendar; timestamps retain UTC offsets.",
        },
    )


def provenance(store: LedgerStore) -> dict[str, Any]:
    """Identify the selected dataset without falsely promising immutable snapshots."""
    with closing(store.connect()) as conn:
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    state = store.sampling_state()
    path = str(store.path.resolve())
    return {
        "dataset_id": "path-sha256:" + hashlib.sha256(path.encode()).hexdigest(),
        "dataset_identity": "Resolved path identity; copies and replacements are not content-addressed.",
        "database_schema_version": schema,
        "latest_sample": store.latest_delta_timestamp(),
        "last_success": state.get("last_success"),
        "available_rollups": store.rollup_bounds(),
        "read_completed_at": datetime.now().astimezone().isoformat(),
        "consistency": "live_non_atomic",
        "timezone": "Recorded local calendar dates; per-sample timestamps carry offsets.",
    }


def query_response(operation: str, store: LedgerStore, **query: Any) -> dict[str, Any]:
    started_at = datetime.now().astimezone().isoformat()
    warnings, actions = [], []
    if operation == "explore":
        query = {
            "by": "process", "process": "", "host": "", "route": "",
            "limit": 50, "offset": 0, "sort": "total", **query,
        }
        data = explore(store, **query)
        if data["coverage"]["status"] != "complete":
            warnings.append(warning_item(
                "sampling_coverage_incomplete",
                "Coverage is partial or unknown. Zero observed bytes do not establish zero traffic.",
            ))
        if data["retained_detail"]["status"] == "partial":
            warnings.append(warning_item(
                "retained_detail_incomplete",
                "Some detail has been removed; totals describe retained detail only.",
            ))
    elif operation == "audit":
        query = {"window_days": 7, "baseline_days": 30, "case_limit": 50, **query}
        data, warnings, actions = audit_traffic(store, **query)
    elif operation == "evidence":
        query = {"limit": 20, **query}
        case = find_case(store, query["case_id"])
        data = build_evidence(store, case, limit=query["limit"])
        warnings.append(warning_item(
            "live_case_recomputed",
            "Case IDs identify policy and query, not an immutable snapshot. Evidence uses current retained data.",
        ))
    else:
        raise ValueError("Unknown read operation")
    result = envelope(operation, data, warnings=warnings, next_actions=actions)
    result["query"] = query
    result["provenance"] = {**provenance(store), "read_started_at": started_at}
    return result
