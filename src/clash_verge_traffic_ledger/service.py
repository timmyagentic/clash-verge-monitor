from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path
from typing import Callable


DEFAULT_LABEL = "com.timmy.clash-verge-traffic-ledger"
Runner = Callable[..., subprocess.CompletedProcess]


def default_plist_path(label: str = DEFAULT_LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def build_launchd_plist(
    label: str,
    python: str,
    working_directory: str,
    database: str,
    controller: str,
    interval: float,
    stdout_path: str,
    stderr_path: str,
    secret: str | None = None,
) -> bytes:
    arguments = [
        python,
        "-m",
        "clash_verge_traffic_ledger",
        "run",
        "--interval",
        f"{interval:g}",
        "--database",
        database,
        "--controller",
        controller,
    ]
    if secret:
        arguments.extend(["--secret", secret])

    payload = {
        "Label": label,
        "ProgramArguments": arguments,
        "WorkingDirectory": working_directory,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
    }
    return plistlib.dumps(payload, sort_keys=False)


def write_launchd_plist(path: str | Path, payload: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def bootstrap_service(
    label: str,
    plist_path: str | Path,
    runner: Runner = subprocess.run,
) -> None:
    domain = f"gui/{os.getuid()}"
    runner(["launchctl", "bootstrap", domain, str(plist_path)], check=False)
    runner(["launchctl", "enable", f"{domain}/{label}"], check=True)
    runner(["launchctl", "kickstart", "-k", f"{domain}/{label}"], check=True)


def bootout_service(
    label: str,
    plist_path: str | Path,
    runner: Runner = subprocess.run,
) -> None:
    domain = f"gui/{os.getuid()}"
    runner(["launchctl", "bootout", domain, str(plist_path)], check=False)
    runner(["launchctl", "disable", f"{domain}/{label}"], check=False)


def service_state(
    label: str = DEFAULT_LABEL,
    runner: Runner = subprocess.run,
) -> str:
    domain = f"gui/{os.getuid()}/{label}"
    completed = runner(
        ["launchctl", "print", domain],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return "not loaded"
    output = completed.stdout or ""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("state ="):
            return stripped.split("=", 1)[1].strip()
    return "loaded"
