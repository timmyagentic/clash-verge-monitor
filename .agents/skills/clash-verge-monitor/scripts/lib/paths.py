from __future__ import annotations

import json
import plistlib
from pathlib import Path
from typing import Any


APP_NAME = "clash-verge-monitor"
LEGACY_APP_NAME = "clash-verge-traffic-ledger"
SAMPLER_LABEL = "com.timmy.clash-verge-monitor"
LEGACY_LABEL = "com.timmy.clash-verge-traffic-ledger"


def default_app_root() -> Path:
    base = Path.home() / "Library" / "Application Support"
    # Never silently switch an existing installation to an empty database.
    current, legacy = base / APP_NAME, base / LEGACY_APP_NAME
    if current.exists() and legacy.exists():
        raise ValueError("Both current and legacy installation directories exist; select --app-root explicitly")
    return legacy if legacy.exists() else current


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
            root / "src" / "clash_verge_monitor"
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


def service_labels(app_root: Path, launch_agents_dir: Path) -> tuple[str, str]:
    """Retain an existing service identity; fresh installs use Monitor labels."""
    if all((launch_agents_dir / f"{label}.plist").exists()
           for label in (SAMPLER_LABEL, LEGACY_LABEL)):
        raise ValueError("Both service identities exist; resolve the duplicate installation before updating")
    manifest = load_manifest(app_root) or {}
    sampler = Path(manifest.get("sampler_plist", "")).stem
    if sampler not in (SAMPLER_LABEL, LEGACY_LABEL):
        sampler = SAMPLER_LABEL
        legacy = launch_agents_dir / f"{LEGACY_LABEL}.plist"
        if legacy.is_file():
            # A legacy service outside this app root must not be adopted implicitly.
            content = plistlib.loads(legacy.read_bytes())
            working_directory = content.get("WorkingDirectory")
            if not working_directory or Path(working_directory).resolve() != app_root.resolve():
                raise ValueError("Legacy service belongs to another installation; select its --app-root explicitly")
            sampler = LEGACY_LABEL
    other = LEGACY_LABEL if sampler == SAMPLER_LABEL else SAMPLER_LABEL
    if (launch_agents_dir / f"{other}.plist").exists():
        raise ValueError("Both service identities exist; resolve the duplicate installation before updating")
    return sampler, f"{sampler}.web"
