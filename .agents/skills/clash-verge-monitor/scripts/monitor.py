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
DEFAULT_LABEL = "com.timmy.clash-verge-monitor"


class MachineParser(argparse.ArgumentParser):
    def error(self, message):
        emit(payload(self.prog.split()[-1], None, ok=False,
                     errors=[error('invalid_arguments', message)]))
        self.exit(2)


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-root", default=None)
    parser.add_argument("--database", default=None)
    parser.add_argument("--runtime-python", default=None)
    parser.add_argument("--runtime-source", default=None, help="Explicit source checkout; overrides installed runtime")
    parser.add_argument("--pretty", action="store_true")


def executable_path(value: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def build_parser() -> argparse.ArgumentParser:
    parser = MachineParser(description="Agent-facing Clash Verge traffic audit wrapper")
    commands = parser.add_subparsers(dest="command", required=True)

    capabilities = commands.add_parser('capabilities', help='Discover the selected runtime capabilities')
    add_runtime_args(capabilities)
    explore = commands.add_parser('explore', help='Query retained traffic with bounded pagination')
    add_runtime_args(explore)
    explore.add_argument('--start', required=True)
    explore.add_argument('--end', required=True)
    explore.add_argument('--by', choices=['process','host','route','hour','minute','connection','rule','chain'], default='process')
    for name in ['process','host','route']:
        explore.add_argument('--' + name, default='')
    explore.add_argument('--limit', type=int, default=50)
    explore.add_argument('--offset', type=int, default=0)
    explore.add_argument('--sort', choices=['total','upload','download','time'], default='total')

    health = commands.add_parser("health", help="Check installation, sampler, database, and controller")
    add_runtime_args(health)
    health.add_argument("--controller", default=None)
    health.add_argument("--secret-file", default=None)
    health.add_argument("--service-label", default=None)
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
    if args.runtime_source:
        source = Path(args.runtime_source).expanduser().resolve()
        if not (source / 'src' / 'clash_verge_monitor' / '__main__.py').is_file():
            raise FileNotFoundError('runtime source is not a ledger checkout')

    runtime_python: Path | None = None
    if args.runtime_python:
        runtime_python = executable_path(args.runtime_python)
    elif args.runtime_source:
        runtime_python = executable_path(sys.executable)
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
    if args.runtime_source:
        environment["PYTHONPATH"] = str(source / "src")
        environment.pop("PYTHONHOME", None)
    elif manifest:
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
    values = ["-m", getattr(args, "runtime_module", "clash_verge_monitor"), core_command]
    if args.command == 'capabilities':
        return values
    values += ["--database", str(database)]
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
    elif args.command == 'explore':
        for name in ['start','end','by','process','host','route','limit','offset','sort']:
            values += ['--' + name, str(getattr(args, name))]
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

    manifest = load_manifest(Path(args.app_root).expanduser().resolve()) or {}
    selection = {
        'mode': 'source' if args.runtime_source else 'explicit_python' if args.runtime_python else 'installed' if manifest else 'source_fallback',
        'python': str(runtime_python),
        'source': str(Path(args.runtime_source).expanduser().resolve()) if args.runtime_source else None,
        'database': str(database),
        'installed_version': manifest.get('version'),
    }
    args.runtime_module = "clash_verge_monitor"
    if manifest and not args.runtime_source and not args.runtime_python:
        args.runtime_module = manifest.get("runtime_module", "clash_verge_traffic_ledger")
    if args.command == 'health' and args.service_label is None:
        args.service_label = Path(manifest["sampler_plist"]).stem if manifest.get("sampler_plist") else DEFAULT_LABEL
    if args.command == 'health' and args.controller is None:
        manifest = load_manifest(Path(args.app_root).expanduser().resolve()) or {}
        args.controller = manifest.get('controller') or DEFAULT_CONTROLLER
    if args.command in ('explore', 'capabilities'):
        probe = subprocess.run([str(runtime_python), '-m', args.runtime_module, 'capabilities'],
                               capture_output=True, text=True, env=environment, check=False)
        try:
            supported = json.loads(probe.stdout)
            compatible = probe.returncode == 0 and args.command in supported['data']['commands']
        except (ValueError, KeyError, TypeError):
            compatible = False
        if not compatible:
            document = payload(args.command, None, ok=False,
                errors=[error('runtime_upgrade_required', 'Selected runtime does not advertise this command.')],
                next_actions=[action('select_compatible_runtime',
                    'Use --runtime-source <checkout> or an explicitly installed compatible runtime. No runtime was changed.')])
            document['runtime_selection'] = selection
            emit(document, pretty=args.pretty)
            return 3
    completed = probe if args.command == 'capabilities' else subprocess.run(
        [str(runtime_python), *core_arguments(args, database)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    try:
        document: dict[str, Any] = json.loads(completed.stdout)
        if not isinstance(document, dict) or not {'schema_version', 'operation', 'ok', 'data', 'errors', 'warnings', 'next_actions'} <= document.keys():
            raise ValueError('runtime output is not a ledger response envelope')
    except (ValueError, TypeError) as exc:
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

    document['runtime_selection'] = selection
    emit(document, pretty=args.pretty)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.app_root is None:
            args.app_root = str(default_app_root())
        return invoke(args)
    except OSError as exc:
        emit(payload(args.command, None, ok=False, errors=[error('runtime_unavailable', str(exc))]), pretty=args.pretty)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
