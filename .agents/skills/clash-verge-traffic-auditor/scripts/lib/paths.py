from __future__ import annotations

import json
from pathlib import Path
from typing import Any


APP_NAME = "clash-verge-traffic-ledger"


def default_app_root() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def default_launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def discover_source(explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "pyproject.toml").is_file() and (
            root / "src" / "clash_verge_traffic_ledger"
        ).is_dir():
            return root
    return None


def load_manifest(app_root: Path) -> dict[str, Any] | None:
    path = app_root / "install.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
