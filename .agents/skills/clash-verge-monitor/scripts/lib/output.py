from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def payload(
    operation: str,
    data: Any,
    *,
    ok: bool = True,
    warnings: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    next_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "ok": ok,
        "operation": operation,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "warnings": warnings or [],
        "errors": errors or [],
        "next_actions": next_actions or [],
    }


def error(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


def action(code: str, description: str, **parameters: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "description": description}
    if parameters:
        item["parameters"] = parameters
    return item


def emit(document: dict[str, Any], *, pretty: bool = False) -> None:
    print(
        json.dumps(
            document,
            ensure_ascii=True,
            indent=2 if pretty else None,
            sort_keys=True,
            separators=None if pretty else (",", ":"),
        )
    )
