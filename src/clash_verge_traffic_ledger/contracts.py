from __future__ import annotations

import json
import argparse
import sqlite3
from . import __version__
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
        "runtime": {"name": "clash-verge-traffic-ledger", "version": __version__},
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


class MachineArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(render_json(envelope(self.prog.split()[-1], None, ok=False,
            errors=[error_item('invalid_arguments', message)])))
        self.exit(2)


def exception_response(operation, exc):
    if isinstance(exc, FileNotFoundError):
        code, exit_code = 'database_missing', EXIT_UNAVAILABLE
    elif isinstance(exc, (ValueError, TypeError, LookupError)):
        code, exit_code = ('case_not_found' if isinstance(exc, LookupError) else 'invalid_request'), EXIT_DATA_ERROR
    elif isinstance(exc, (OSError, sqlite3.OperationalError)):
        code, exit_code = 'resource_unavailable', EXIT_UNAVAILABLE
    elif isinstance(exc, sqlite3.DatabaseError):
        code, exit_code = 'invalid_database', EXIT_DATA_ERROR
    else:
        code, exit_code = 'operation_failed', EXIT_OPERATIONAL_ERROR
    return envelope(operation, None, ok=False, errors=[error_item(code, str(exc),
        retryable=isinstance(exc, sqlite3.OperationalError) and 'locked' in str(exc).lower())]), exit_code
