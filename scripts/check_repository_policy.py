#!/usr/bin/env python3
"""Check sequential stable versions, Skill metadata and pinned CI actions."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

from check_release import ROOT, project_version, validation_errors


STABLE = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def stable_version(value: str) -> tuple[int, int, int] | None:
    match = STABLE.fullmatch(value)
    return tuple(map(int, match.groups())) if match else None


def patch_version_errors(version: str, tags: list[str]) -> list[str]:
    current = stable_version(version)
    if current is None:
        return ["source version must be a stable MAJOR.MINOR.PATCH version"]
    versions = sorted({v for tag in tags if (v := stable_version(tag)) is not None})
    if not versions:
        return ["no stable release baseline; fetch the repository tags"]
    if current < versions[-1]:
        return ["source version is older than the latest stable tag"]
    previous = [v for v in versions if v != current]
    if not previous:
        return []
    major, minor, patch = previous[-1]
    if current != (major, minor, patch + 1):
        return [f"stable versions must advance one patch from {major}.{minor}.{patch}"]
    return []


def source_policy_errors(root: Path) -> list[str]:
    import yaml

    errors = []
    skill = root / ".agents/skills/clash-verge-traffic-auditor/SKILL.md"
    parts = skill.read_text().split("---", 2)
    metadata = yaml.safe_load(parts[1]) if len(parts) == 3 else {}
    if metadata.get("name") != "clash-verge-traffic-auditor" or not metadata.get("description"):
        errors.append("Skill name and description are required")
    for path in (root / ".github/workflows").glob("*.yml"):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        if "pull_request_target" in workflow.get("on", {}):
            errors.append(f"{path.name}: privileged pull_request_target is forbidden")
        if workflow.get("permissions", {}).get("contents") != "read":
            errors.append(f"{path.name}: default contents permission must be read")
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses", "")
                if action and not re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action):
                    errors.append(f"{path.name}: external actions must use full commit SHAs")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--tag")
    args = parser.parse_args()
    tags = subprocess.check_output(["git", "tag", "--list"], cwd=ROOT, text=True).splitlines()
    errors = validation_errors(tag=args.tag, allow_dirty=args.allow_dirty)
    errors += patch_version_errors(project_version(), tags)
    errors += source_policy_errors(ROOT)
    for error in errors:
        print(f"error: {error}")
    if not errors:
        print(f"Repository policy OK: {project_version()}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
