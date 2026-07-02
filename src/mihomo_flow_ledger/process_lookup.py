from __future__ import annotations

import shutil
import subprocess


CORE_PROCESS_MARKERS = (
    "verge-mihomo",
    "mihomo",
    "clash-verge",
    "clash verge",
    "clash-meta",
)


def lsof_path() -> str | None:
    return shutil.which("lsof") or "/usr/sbin/lsof"


def parse_lsof_process_names(output: str) -> list[str]:
    names: list[str] = []
    for line in output.splitlines():
        if line.startswith("c") and len(line) > 1:
            name = line[1:].strip()
            if name:
                names.append(name)
    return names


def choose_process_name(names: list[str]) -> str | None:
    if not names:
        return None
    for name in names:
        lowered = name.lower()
        if not any(marker in lowered for marker in CORE_PROCESS_MARKERS):
            return name
    return names[0]


def lookup_process_name(source_port: int, timeout: float = 2.0) -> str | None:
    executable = lsof_path()
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "-nP", f"-iTCP:{source_port}", "-F", "c"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):
        return None
    return choose_process_name(parse_lsof_process_names(result.stdout))

