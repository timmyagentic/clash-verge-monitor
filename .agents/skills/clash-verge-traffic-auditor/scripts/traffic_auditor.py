#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from lib.output import action, emit, error, payload
from lib.paths import default_app_root, discover_source, load_manifest


DEFAULT_CONTROLLER = "auto"
DEFAULT_LABEL = "com.timmy.clash-verge-traffic-ledger"


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-root", default=str(default_app_root()))
    parser.add_argument("--database", default=None)
    parser.add_argument("--runtime-python", default=None)
    parser.add_argument("--pretty", action="store_true")


def executable_path(value: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent-facing Clash Verge traffic audit wrapper")
    commands = parser.add_subparsers(dest="command", required=True)

    health = commands.add_parser("health", help="Check installation, sampler, database, and controller")
    add_runtime_args(health)
    health.add_argument("--controller", default=None)
    health.add_argument("--secret-file", default=None)
    health.add_argument("--service-label", default=DEFAULT_LABEL)
    health.add_argument("--max-sample-age", type=float, default=180.0)
    health.add_argument("--no-controller-check", action="store_true")
    health.add_argument("--no-service-check", action="store_true")

    audit = commands.add_parser("audit", help="Audit a recent window")
    add_runtime_args(audit)
    audit.add_argument("--end-date", default=None)
    audit.add_argument("--since", type=int, default=7)
    audit.add_argument("--baseline", type=int, default=30)
    audit.add_argument("--limit", type=int, default=50)

    evidence = commands.add_parser("evidence", help="Expand one audit case")
    add_runtime_args(evidence)
    evidence.add_argument("--case-id", required=True)
    evidence.add_argument("--limit", type=int, default=20)

    maintain = commands.add_parser("maintain", help="Plan or apply raw-data retention")
    add_runtime_args(maintain)
    maintain.add_argument("--before", required=True)
    maintain.add_argument("--mode", choices=["compact", "prune"], default="compact")
    maintain_mode = maintain.add_mutually_exclusive_group()
    maintain_mode.add_argument("--apply", action="store_true")
    maintain_mode.add_argument("--dry-run", action="store_true")

    return parser


def resolve_runtime(args: argparse.Namespace) -> tuple[Path, Path, dict[str, str]]:
    app_root = Path(args.app_root).expanduser().resolve()
    manifest = load_manifest(app_root)
    source = discover_source()

    runtime_python: Path | None = None
    if args.runtime_python:
        runtime_python = executable_path(args.runtime_python)
    elif manifest and manifest.get("runtime_python"):
        runtime_python = executable_path(str(manifest["runtime_python"]))
    elif source:
        runtime_python = executable_path(sys.executable)

    if not runtime_python or not runtime_python.is_file():
        raise FileNotFoundError(
            "no installed runtime was found; run bootstrap.py install with a repository source"
        )

    if args.database:
        database = Path(args.database).expanduser().resolve()
    elif manifest and manifest.get("database"):
        database = Path(str(manifest["database"])).expanduser().resolve()
    elif source and (source / "data" / "ledger.sqlite").is_file():
        database = (source / "data" / "ledger.sqlite").resolve()
    else:
        database = app_root / "data" / "ledger.sqlite"

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    if manifest:
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
    elif source:
        existing = environment.get("PYTHONPATH")
        source_path = str(source / "src")
        environment["PYTHONPATH"] = (
            source_path if not existing else f"{source_path}{os.pathsep}{existing}"
        )
    return runtime_python, database, environment


def core_arguments(args: argparse.Namespace, database: Path) -> list[str]:
    core_command = "maintenance" if args.command == "maintain" else args.command
    values = ["-m", "clash_verge_traffic_ledger", core_command, "--database", str(database)]
    if args.command == "health":
        values.extend(
            [
                "--controller",
                args.controller,
                "--service-label",
                args.service_label,
                "--max-sample-age",
                str(args.max_sample_age),
            ]
        )
        if args.secret_file:
            values.extend(["--secret-file", str(Path(args.secret_file).expanduser().resolve())])
        if args.no_controller_check:
            values.append("--no-controller-check")
        if args.no_service_check:
            values.append("--no-service-check")
    elif args.command == "audit":
        values.extend(["--since", str(args.since), "--baseline", str(args.baseline), "--limit", str(args.limit)])
        if args.end_date:
            values.extend(["--end-date", args.end_date])
    elif args.command == "evidence":
        values.extend(["--case-id", args.case_id, "--limit", str(args.limit)])
    else:
        values.extend(["--before", args.before, "--mode", args.mode])
        values.append("--apply" if args.apply else "--dry-run")
    return values


def invoke(args: argparse.Namespace) -> int:
    try:
        runtime_python, database, environment = resolve_runtime(args)
    except Exception as exc:
        emit(
            payload(
                args.command,
                None,
                ok=False,
                errors=[error("runtime_unavailable", str(exc))],
                next_actions=[
                    action(
                        "bootstrap_runtime",
                        "Run the bundled bootstrap install command before retrying.",
                    )
                ],
            ),
            pretty=args.pretty,
        )
        return 3

    if args.command == 'health' and args.controller is None:
        manifest = load_manifest(Path(args.app_root).expanduser().resolve()) or {}
        args.controller = manifest.get('controller') or DEFAULT_CONTROLLER
    completed = subprocess.run(
        [str(runtime_python), *core_arguments(args, database)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    try:
        document: dict[str, Any] = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        emit(
            payload(
                args.command,
                None,
                ok=False,
                errors=[
                    error(
                        "invalid_runtime_output",
                        f"runtime returned non-JSON output: {exc}",
                        retryable=True,
                    )
                ],
                next_actions=[
                    action(
                        "inspect_runtime_stderr",
                        "Inspect the runtime error before retrying.",
                        stderr=completed.stderr[-2000:],
                    )
                ],
            ),
            pretty=args.pretty,
        )
        return completed.returncode or 4

    emit(document, pretty=args.pretty)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    return invoke(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
