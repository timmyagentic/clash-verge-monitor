# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 package using a `src/` layout. Runtime code lives in
`src/clash_verge_traffic_ledger/`; `__main__.py` defines the CLI commands,
`client.py` talks to the Mihomo controller, `monitor.py` computes sampled byte
deltas, `store.py` persists SQLite rollups, and `audit.py` produces deterministic
multi-day cases. The project-local Agent Skill lives at
`.agents/skills/clash-verge-traffic-auditor/`; keep its scripts as thin runtime
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
python -m clash_verge_traffic_ledger doctor
python -m clash_verge_traffic_ledger run --interval 1 --database data/ledger.sqlite
python -m clash_verge_traffic_ledger today --database data/ledger.sqlite
python -m clash_verge_traffic_ledger audit --database data/ledger.sqlite --since 7 --pretty
```

Run the test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" \
  .agents/skills/clash-verge-traffic-auditor
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
brief and MVP status` and `Rename project for Clash Verge traffic ledger`.
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
