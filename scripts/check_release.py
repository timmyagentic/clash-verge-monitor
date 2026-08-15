#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def project_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def package_version(root: Path = ROOT) -> str:
    source = root / "src" / "clash_verge_traffic_ledger" / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__version__" for target in statement.targets):
            continue
        if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            return statement.value.value
    raise ValueError(f"__version__ string not found in {source}")


def changelog_release_label(version: str, root: Path = ROOT) -> str | None:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\] - (.+)$", changelog, re.MULTILINE)
    return match.group(1).strip() if match else None


def changelog_release_notes(version: str, root: Path = ROOT) -> str | None:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^## \[{re.escape(version)}\] - [^\n]+\n(?P<body>.*?)(?=^## \[|\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() + "\n" if match else None


def normalized_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def git_changes(root: Path = ROOT) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def distribution_errors(dist_dir: Path, version: str) -> list[str]:
    errors: list[str] = []
    normalized_name = "clash_verge_traffic_ledger"
    sdist = dist_dir / f"{normalized_name}-{version}.tar.gz"
    wheel = dist_dir / f"{normalized_name}-{version}-py3-none-any.whl"
    for artifact in [sdist, wheel]:
        if not artifact.is_file():
            errors.append(f"missing distribution artifact: {artifact}")
    if errors:
        return errors

    with tarfile.open(sdist, "r:gz") as archive:
        sdist_names = archive.getnames()
    required_sdist_suffixes = [
        "/.agents/skills/clash-verge-traffic-auditor/SKILL.md",
        "/CHANGELOG.md",
        "/docs/releasing.md",
        "/scripts/check_release.py",
        "/src/clash_verge_traffic_ledger/__init__.py",
    ]
    for suffix in required_sdist_suffixes:
        if not any(name.endswith(suffix) for name in sdist_names):
            errors.append(f"sdist is missing required content: {suffix}")

    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    required_wheel_suffixes = [
        "clash_verge_traffic_ledger/__init__.py",
        f"{normalized_name}-{version}.dist-info/METADATA",
        f"{normalized_name}-{version}.dist-info/entry_points.txt",
    ]
    for suffix in required_wheel_suffixes:
        if not any(name.endswith(suffix) for name in wheel_names):
            errors.append(f"wheel is missing required content: {suffix}")

    for artifact, names in [(sdist, sdist_names), (wheel, wheel_names)]:
        forbidden = [
            name
            for name in names
            if "__pycache__" in name or name.endswith((".pyc", ".pyo"))
        ]
        if forbidden:
            errors.append(
                f"{artifact.name} contains generated Python cache files: "
                + ", ".join(forbidden[:5])
            )
    return errors


def validation_errors(
    root: Path = ROOT,
    *,
    tag: str | None = None,
    allow_dirty: bool = False,
) -> list[str]:
    errors: list[str] = []
    metadata_version = project_version(root)
    runtime_version = package_version(root)
    if metadata_version != runtime_version:
        errors.append(
            f"version mismatch: pyproject.toml={metadata_version}, package={runtime_version}"
        )

    release_label = changelog_release_label(metadata_version, root)
    if release_label is None:
        errors.append(f"CHANGELOG.md has no [{metadata_version}] release section")

    if tag is not None:
        tag_version = normalized_tag(tag)
        if tag_version != metadata_version:
            errors.append(f"tag {tag} does not match version {metadata_version}")
        if release_label == "Unreleased":
            errors.append(
                f"CHANGELOG.md [{metadata_version}] is still marked Unreleased"
            )

    if not allow_dirty:
        changes = git_changes(root)
        if changes:
            errors.append(
                "release source is dirty; commit or remove these changes first:\n"
                + "\n".join(changes)
            )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate release metadata and the clean-source boundary."
    )
    parser.add_argument("--tag", help="Expected release tag, for example v0.3.0")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a dirty worktree during release preparation; never use for publication.",
    )
    parser.add_argument(
        "--notes-output",
        type=Path,
        help="Write only the current version section body to this release-notes file.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        help="Validate the wheel and sdist in this directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = validation_errors(tag=args.tag, allow_dirty=args.allow_dirty)
    if args.dist_dir:
        errors.extend(distribution_errors(args.dist_dir, project_version()))
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    version = project_version()
    if args.notes_output:
        notes = changelog_release_notes(version)
        if notes is None:
            print(f"error: no release notes found for {version}", file=sys.stderr)
            return 1
        args.notes_output.parent.mkdir(parents=True, exist_ok=True)
        args.notes_output.write_text(notes, encoding="utf-8")
        print(f"release notes: {args.notes_output}")
    print(f"release metadata OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
