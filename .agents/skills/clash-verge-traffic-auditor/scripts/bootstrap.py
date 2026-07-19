#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.output import action, emit, error, payload
from lib.paths import default_app_root, default_launch_agents_dir, discover_source, load_manifest


SAMPLER_LABEL = "com.timmy.clash-verge-traffic-ledger"
WEB_LABEL = f"{SAMPLER_LABEL}.web"
DEFAULT_CONTROLLER = "/tmp/verge/verge-mihomo.sock"


def add_path_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-root", default=str(default_app_root()))
    parser.add_argument("--launch-agents-dir", default=str(default_launch_agents_dir()))
    parser.add_argument("--pretty", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the traffic ledger into a stable local runtime")
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="Inspect installation state without writing")
    add_path_args(status)

    install = commands.add_parser("install", help="Install or update the stable runtime")
    add_path_args(install)
    install.add_argument("--source", default=None, help="Repository root; auto-detected project-locally")
    install.add_argument("--database", default=None, help="Existing database to adopt without moving")
    install.add_argument("--controller", default=DEFAULT_CONTROLLER)
    install.add_argument("--secret-file", default=None)
    install.add_argument("--interval", type=float, default=1.0)
    install.add_argument("--max-backoff", type=float, default=30.0)
    install.add_argument("--host", default="127.0.0.1")
    install.add_argument("--port", type=int, default=8765)
    install.add_argument("--bootstrap-python", default=sys.executable)
    install.add_argument("--load", action="store_true", help="Load and restart both LaunchAgents")
    install.add_argument("--dry-run", action="store_true", help="Print the plan without writing")

    uninstall = commands.add_parser("uninstall", help="Plan or apply runtime removal while keeping data")
    add_path_args(uninstall)
    uninstall.add_argument("--apply", action="store_true", help="Apply the displayed removal plan")
    uninstall.add_argument("--keep-runtime", action="store_true")
    uninstall.add_argument("--keep-plists", action="store_true")

    return parser


def absolute(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def read_version(source: Path) -> str:
    with (source / "pyproject.toml").open("rb") as handle:
        value = tomllib.load(handle)["project"]["version"]
    return str(value)


def source_revision(source: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def validate_source(source: Path | None) -> Path:
    if not source:
        raise FileNotFoundError(
            "repository source not found; pass --source or run from the project-local skill"
        )
    package = source / "src" / "clash_verge_traffic_ledger"
    if not package.is_dir() or not (source / "pyproject.toml").is_file():
        raise FileNotFoundError(f"invalid repository source: {source}")
    return source


def validate_secret_file(value: str | None) -> Path | None:
    if not value:
        return None
    path = absolute(value)
    if not path.is_file():
        raise FileNotFoundError(f"secret file not found: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise PermissionError(f"secret file must use mode 600 or stricter: {path}")
    if not path.read_text(encoding="utf-8").strip():
        raise ValueError(f"secret file is empty: {path}")
    return path


def parse_launchctl_output(output: str) -> dict[str, str | None]:
    state = None
    plist = None
    for line in output.splitlines():
        stripped = line.strip()
        if state is None and stripped.startswith("state ="):
            state = stripped.split("=", 1)[1].strip()
        elif plist is None and stripped.startswith("path ="):
            plist = stripped.split("=", 1)[1].strip()
    return {"state": state or "loaded", "plist": plist}


def launchctl_details(label: str) -> dict[str, str | None]:
    completed = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {"state": "not loaded", "plist": None}
    return parse_launchctl_output(completed.stdout)


def launchctl_state(label: str) -> str:
    return str(launchctl_details(label)["state"])


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.chmod(mode)
    os.replace(temporary, path)


def backup_and_write_plist(path: Path, content: bytes, backup_dir: Path) -> str | None:
    if path.is_file() and path.read_bytes() == content:
        return None
    backup: Path | None = None
    if path.is_file():
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = backup_dir / f"{path.name}.{timestamp}.bak"
        shutil.copy2(path, backup)
    atomic_write(path, content)
    return str(backup) if backup else None


def launchd_payload(
    *,
    label: str,
    arguments: list[str],
    working_directory: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> bytes:
    return plistlib.dumps(
        {
            "Label": label,
            "ProgramArguments": arguments,
            "WorkingDirectory": str(working_directory),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "StandardOutPath": str(stdout_path),
            "StandardErrorPath": str(stderr_path),
        },
        sort_keys=False,
    )


def install_runtime(source: Path, runtime_root: Path, bootstrap_python: Path) -> Path:
    venv_root = runtime_root / "venv"
    runtime_python = venv_root / "bin" / "python"
    if not runtime_python.is_file():
        if venv_root.exists():
            shutil.rmtree(venv_root)
        runtime_root.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(bootstrap_python), "-m", "venv", str(venv_root)], check=True)

    source_root = runtime_root / "src"
    source_root.mkdir(parents=True, exist_ok=True)
    package_target = source_root / "clash_verge_traffic_ledger"
    staged = source_root / f".package-{uuid.uuid4().hex}"
    shutil.copytree(
        source / "src" / "clash_verge_traffic_ledger",
        staged,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    previous = source_root / f".previous-{uuid.uuid4().hex}"
    if package_target.exists():
        package_target.rename(previous)
    staged.rename(package_target)
    if previous.exists():
        shutil.rmtree(previous)

    clean_environment = os.environ.copy()
    clean_environment.pop("PYTHONPATH", None)
    clean_environment.pop("PYTHONHOME", None)
    completed = subprocess.run(
        [str(runtime_python), "-c", "import site; print(site.getsitepackages()[0])"],
        capture_output=True,
        text=True,
        env=clean_environment,
        check=True,
    )
    site_packages = Path(completed.stdout.strip())
    atomic_write(
        site_packages / "clash_verge_traffic_ledger.pth",
        f"{source_root}\n".encode("utf-8"),
    )
    subprocess.run(
        [
            str(runtime_python),
            "-c",
            "import clash_verge_traffic_ledger as p; print(p.__version__)",
        ],
        capture_output=True,
        text=True,
        env=clean_environment,
        check=True,
    )
    return runtime_python


def load_service(label: str, plist: Path) -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], check=False)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{label}"], check=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], check=True)


def unload_service(label: str, plist: Path) -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], check=False)
    subprocess.run(["launchctl", "disable", f"{domain}/{label}"], check=False)


def installation_status(app_root: Path, launch_agents_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(app_root)
    runtime_python = (
        Path(os.path.abspath(os.path.expanduser(str(manifest["runtime_python"]))))
        if manifest and manifest.get("runtime_python")
        else None
    )
    database = (
        absolute(str(manifest["database"])) if manifest and manifest.get("database") else None
    )
    sampler_details = launchctl_details(SAMPLER_LABEL)
    web_details = launchctl_details(WEB_LABEL)
    return {
        "installed": bool(manifest and runtime_python and runtime_python.is_file()),
        "app_root": str(app_root),
        "manifest": str(app_root / "install.json"),
        "runtime_python": str(runtime_python) if runtime_python else None,
        "runtime_exists": bool(runtime_python and runtime_python.is_file()),
        "database": str(database) if database else None,
        "database_exists": bool(database and database.is_file()),
        "services": {
            "sampler": {
                "label": SAMPLER_LABEL,
                "state": sampler_details["state"],
                "plist": str(launch_agents_dir / f"{SAMPLER_LABEL}.plist"),
                "loaded_plist": sampler_details["plist"],
            },
            "web": {
                "label": WEB_LABEL,
                "state": web_details["state"],
                "plist": str(launch_agents_dir / f"{WEB_LABEL}.plist"),
                "loaded_plist": web_details["plist"],
            },
        },
        "configuration": manifest,
    }


def command_status(args: argparse.Namespace) -> int:
    app_root = absolute(args.app_root)
    launch_agents_dir = absolute(args.launch_agents_dir)
    data = installation_status(app_root, launch_agents_dir)
    next_actions = []
    if not data["installed"]:
        next_actions.append(
            action("install_runtime", "Run bootstrap.py install with a repository source.")
        )
    emit(payload("bootstrap_status", data, next_actions=next_actions), pretty=args.pretty)
    return 0


def command_install(args: argparse.Namespace) -> int:
    try:
        source = validate_source(discover_source(args.source))
        if args.interval <= 0 or args.max_backoff < args.interval:
            raise ValueError("max backoff must be at least the positive polling interval")
        secret_file = validate_secret_file(args.secret_file)
        app_root = absolute(args.app_root)
        launch_agents_dir = absolute(args.launch_agents_dir)
        version = read_version(source)
        runtime_root = app_root / "runtime" / version
        runtime_python = runtime_root / "venv" / "bin" / "python"
        if args.database:
            database = absolute(args.database)
        elif (source / "data" / "ledger.sqlite").is_file():
            database = (source / "data" / "ledger.sqlite").resolve()
        else:
            database = app_root / "data" / "ledger.sqlite"
        sampler_plist = launch_agents_dir / f"{SAMPLER_LABEL}.plist"
        web_plist = launch_agents_dir / f"{WEB_LABEL}.plist"
        plan = {
            "source": str(source),
            "version": version,
            "app_root": str(app_root),
            "runtime_python": str(runtime_python),
            "database": str(database),
            "database_action": "adopt_existing" if database.is_file() else "create_on_first_sample",
            "sampler_plist": str(sampler_plist),
            "web_plist": str(web_plist),
            "load_services": args.load,
            "secret_file": str(secret_file) if secret_file else None,
        }
        if args.dry_run:
            emit(payload("bootstrap_install", {"dry_run": True, "plan": plan}), pretty=args.pretty)
            return 0

        logs = app_root / "logs"
        for directory in [app_root, app_root / "data", logs, app_root / "backups"]:
            directory.mkdir(parents=True, exist_ok=True)
        runtime_python = install_runtime(source, runtime_root, absolute(args.bootstrap_python))

        sampler_arguments = [
            str(runtime_python),
            "-m",
            "clash_verge_traffic_ledger",
            "run",
            "--interval",
            f"{args.interval:g}",
            "--max-backoff",
            f"{args.max_backoff:g}",
            "--database",
            str(database),
            "--controller",
            args.controller,
        ]
        if secret_file:
            sampler_arguments.extend(["--secret-file", str(secret_file)])
        web_arguments = [
            str(runtime_python),
            "-m",
            "clash_verge_traffic_ledger",
            "web",
            "--database",
            str(database),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        sampler_payload = launchd_payload(
            label=SAMPLER_LABEL,
            arguments=sampler_arguments,
            working_directory=app_root,
            stdout_path=logs / "sampler.out.log",
            stderr_path=logs / "sampler.err.log",
        )
        web_payload = launchd_payload(
            label=WEB_LABEL,
            arguments=web_arguments,
            working_directory=app_root,
            stdout_path=logs / "web.out.log",
            stderr_path=logs / "web.err.log",
        )
        backup_dir = app_root / "backups"
        backups = [
            backup_and_write_plist(sampler_plist, sampler_payload, backup_dir),
            backup_and_write_plist(web_plist, web_payload, backup_dir),
        ]

        previous_manifest = load_manifest(app_root) or {}
        manifest = {
            "schema_version": "1",
            "version": version,
            "source": str(source),
            "source_revision": source_revision(source),
            "runtime_python": str(runtime_python),
            "database": str(database),
            "controller": args.controller,
            "interval_seconds": args.interval,
            "max_backoff_seconds": args.max_backoff,
            "dashboard": f"http://{args.host}:{args.port}/",
            "sampler_plist": str(sampler_plist),
            "web_plist": str(web_plist),
            "secret_file": str(secret_file) if secret_file else None,
            "installed_at": previous_manifest.get("installed_at")
            or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write(
            app_root / "install.json",
            (json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            mode=0o600,
        )
        if args.load:
            load_service(SAMPLER_LABEL, sampler_plist)
            load_service(WEB_LABEL, web_plist)

        emit(
            payload(
                "bootstrap_install",
                {
                    "dry_run": False,
                    "plan": plan,
                    "manifest": manifest,
                    "plist_backups": [item for item in backups if item],
                    "status": installation_status(app_root, launch_agents_dir),
                },
            ),
            pretty=args.pretty,
        )
        return 0
    except Exception as exc:
        emit(
            payload(
                "bootstrap_install",
                None,
                ok=False,
                errors=[error("install_failed", str(exc), retryable=True)],
                next_actions=[
                    action(
                        "inspect_install_inputs",
                        "Check the source path, Python runtime, and secret-file permissions before retrying.",
                    )
                ],
            ),
            pretty=args.pretty,
        )
        return 1


def command_uninstall(args: argparse.Namespace) -> int:
    try:
        app_root = absolute(args.app_root)
        launch_agents_dir = absolute(args.launch_agents_dir)
        runtime_dir = app_root / "runtime"
        sampler_plist = launch_agents_dir / f"{SAMPLER_LABEL}.plist"
        web_plist = launch_agents_dir / f"{WEB_LABEL}.plist"
        plan = {
            "unload_services": True,
            "remove_runtime": not args.keep_runtime,
            "remove_plists": not args.keep_plists,
            "remove_manifest": True,
            "preserve_data": str(app_root / "data"),
            "preserve_logs": str(app_root / "logs"),
        }
        if not args.apply:
            emit(
                payload(
                    "bootstrap_uninstall",
                    {"dry_run": True, "plan": plan},
                    next_actions=[
                        action(
                            "confirm_uninstall",
                            "After explicit user confirmation, rerun with --apply.",
                        )
                    ],
                ),
                pretty=args.pretty,
            )
            return 0

        warnings = []
        for label, plist in [(SAMPLER_LABEL, sampler_plist), (WEB_LABEL, web_plist)]:
            details = launchctl_details(label)
            if details["plist"] == str(plist):
                unload_service(label, plist)
            elif details["state"] != "not loaded":
                warnings.append(
                    {
                        "code": "foreign_service_preserved",
                        "message": f"Left loaded {label} untouched because it uses another plist.",
                        "details": {"loaded_plist": details["plist"], "expected_plist": str(plist)},
                    }
                )
        if not args.keep_plists:
            sampler_plist.unlink(missing_ok=True)
            web_plist.unlink(missing_ok=True)
        if not args.keep_runtime and runtime_dir.is_dir():
            shutil.rmtree(runtime_dir)
        (app_root / "install.json").unlink(missing_ok=True)
        emit(
            payload(
                "bootstrap_uninstall",
                {"dry_run": False, "plan": plan, "status": installation_status(app_root, launch_agents_dir)},
                warnings=warnings,
            ),
            pretty=args.pretty,
        )
        return 0
    except Exception as exc:
        emit(
            payload(
                "bootstrap_uninstall",
                None,
                ok=False,
                errors=[error("uninstall_failed", str(exc), retryable=True)],
            ),
            pretty=args.pretty,
        )
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        return command_status(args)
    if args.command == "install":
        return command_install(args)
    return command_uninstall(args)


if __name__ == "__main__":
    raise SystemExit(main())
