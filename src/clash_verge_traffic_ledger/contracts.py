from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable


SCHEMA_VERSION = "1"

EXIT_OK = 0
EXIT_OPERATIONAL_ERROR = 1
EXIT_UNAVAILABLE = 3
EXIT_DATA_ERROR = 4


def envelope(
    operation: str,
    data: Any,
    *,
    ok: bool = True,
    warnings: Iterable[dict[str, Any] | str] = (),
    errors: Iterable[dict[str, Any] | str] = (),
    next_actions: Iterable[dict[str, Any] | str] = (),
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "operation": operation,
        "generated_at": timestamp.astimezone(timezone.utc).isoformat(),
        "data": data,
        "warnings": list(warnings),
        "errors": list(errors),
        "next_actions": list(next_actions),
    }


def error_item(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if details:
        item["details"] = details
    return item


def warning_item(code: str, message: str, **details: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if details:
        item["details"] = details
    return item


def action_item(code: str, description: str, **parameters: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "description": description}
    if parameters:
        item["parameters"] = parameters
    return item


def render_json(payload: dict[str, Any], *, pretty: bool = False) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        indent=2 if pretty else None,
        sort_keys=True,
        separators=None if pretty else (",", ":"),
    )
