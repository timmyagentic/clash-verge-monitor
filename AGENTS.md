# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 package using a `src/` layout. Runtime code lives in
`src/clash_verge_monitor/`; `__main__.py` defines the CLI commands,
`client.py` talks to the Mihomo controller, `monitor.py` computes sampled byte
deltas, `store.py` persists SQLite rollups, and `audit.py` produces deterministic
multi-day cases. The project-local Agent Skill lives at
`.agents/skills/clash-verge-monitor/`; keep its scripts as thin runtime
orchestration, not duplicate accounting logic.
Tests live in `tests/` and mirror main behaviors. Context and verification notes
live under `docs/`; local databases belong in ignored `data/` paths.

## Build, Test, and Development Commands

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Sets up an editable local install. Use the module form during development:

```bash
python -m clash_verge_monitor doctor
python -m clash_verge_monitor run --interval 1 --database data/ledger.sqlite
python -m clash_verge_monitor today --database data/ledger.sqlite
python -m clash_verge_monitor audit --database data/ledger.sqlite --since 7 --pretty
```

Run the test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" \
  .agents/skills/clash-verge-monitor
```

## Coding Style & Naming Conventions

Use standard Python style: 4-space indentation, `snake_case` for functions and
variables, `PascalCase` for classes, and explicit type hints for public helpers.
Keep modules small and aligned to the current boundaries: controller access,
sampling, process lookup, storage, and reporting. Prefer standard-library
facilities already used here (`argparse`, `pathlib`, `sqlite3`, `unittest`).

## Testing Guidelines

Tests use `unittest` and should be placed in `tests/test_*.py`. Name test
classes with a `Tests` suffix and methods with `test_...`. Use temporary SQLite
files, fixed datetimes, and temporary Application Support roots. Test bootstrap
twice to preserve idempotency. Add regression coverage before changing delta,
baseline, case-ID, read-only, or retention behavior.

## Commit & Pull Request Guidelines

Recent history uses short imperative commit subjects, for example `Add project
brief and MVP status` and `Rename project for Clash Verge Monitor`.
Follow that style and keep each commit focused. Pull requests should describe
the change, list checks run, note live controller or SQLite verification, and
include sample output for CLI changes.

## Security & Configuration Tips

Do not commit local ledgers, secrets, or controller-specific runtime files.
`data/`, `*.sqlite`, and SQLite WAL/SHM files are ignored intentionally. Never
write secrets into plist arguments, logs, JSON, or fixtures. Use
`MIHOMO_SECRET` interactively or a mode-600 secret file for launchd. Audits must
open existing databases read-only; destructive maintenance requires an explicit
`--apply` after reviewing the dry run.

## Merge and Release Policy

- Stable releases advance one patch on the current line (`0.3.0` → `0.3.1` → `0.3.2`); do not introduce minor/major jumps or publish the former `0.4.0rc1` label.
- Main accepts squash merges through PRs after all six required CI checks, an up-to-date base and resolved discussions. No bypass actors are configured. Recheck the exact head and merge with `--match-head-commit`; never use `--admin`.
- Release tags are immutable. A tag must point to verified current main; the Release workflow repeats CI, validates distributions and installs the wheel before publishing.
- Never equate the application version with the database schema. Upgrade an existing schema v2 ledger in place without retention, compaction or row rewriting. Record pre/post preservation and live service evidence.

## Repository workflow and branch protection

- Confirm the current GitHub default branch before starting; it is currently `main`. Fetch it, use a separate `codex/` branch in an isolated worktree, and keep the primary checkout read-only. Under Tingjun Workspace, activate the Task and Session, acknowledge the current Context revision and hold the worktree's unique writer claim.
- All changes to the GitHub default branch must go through a PR. Direct pushes, force pushes and deletion of that branch are prohibited. Administrators and apps have no bypass. Never use `--admin`, disable protection or add a bypass actor to land a change.
- Only squash merging is allowed. Inspect the final diff, current head, review threads and actual verification results before an authorized merge. Resolve all review conversations and address substantive findings; zero mandatory approvals supports the single-maintainer workflow. Merge with `gh pr merge <PR> --squash --match-head-commit <verified-full-head-SHA>` and verify the merged state afterward.
- Keep `delete_branch_on_merge = true` and verify that GitHub automatically removes the merged PR's remote task branch when eligible. Do not use `--delete-branch`, which also removes the local branch. Under Tingjun Workspace, completion only releases the writer claim; local branches and worktrees remain for the existing archive workflow.
- The default-branch ruleset declaration is [`.github/main-ruleset.json`](.github/main-ruleset.json); repository merge and deletion settings are declared in [`.github/repository-settings.json`](.github/repository-settings.json). These files do not apply themselves. After an authorized configuration update, read back the GitHub repository settings, effective rules and any classic branch protection. Protect the actual default branch rather than assuming it is named `main`.
- Preserve the existing CI workflows, trigger conditions, required checks, app bindings and strictness. Existing stronger protections and immutable release tags remain in force. An empty or legitimately path-filtered checks list does not prove application tests passed; report the checks actually run and mark unavailable verification `UNVERIFIED`. Follow this repository's existing verification requirements and use proportionate document/configuration checks for documentation changes.
