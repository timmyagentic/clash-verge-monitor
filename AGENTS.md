# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 package using a `src/` layout. Runtime code lives in
`src/clash_verge_traffic_ledger/`; `__main__.py` defines the CLI commands,
`client.py` talks to the Mihomo controller, `monitor.py` computes sampled byte
deltas, `store.py` persists SQLite rollups, and `reports.py` formats exports.
Tests live in `tests/` and mirror the main behaviors by module. Project context
and design notes are under `docs/`, including `docs/project-brief.zh-CN.md`.
Generated local databases belong in `data/` and are ignored by Git.

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
python -m clash_verge_traffic_ledger export --date 2026-07-02 --format csv --output report.csv
```

Run the test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

If packaging output is needed, install `build` locally and run `python -m build`.

## Coding Style & Naming Conventions

Use standard Python style: 4-space indentation, `snake_case` for functions and
variables, `PascalCase` for classes, and explicit type hints for public helpers.
Keep modules small and aligned to the current boundaries: controller access,
sampling, process lookup, storage, and reporting. Prefer standard-library
facilities already used here (`argparse`, `pathlib`, `sqlite3`, `unittest`) over
adding dependencies without a clear reason.

## Testing Guidelines

Tests use `unittest` and should be placed in `tests/test_*.py`. Name test
classes with a `Tests` suffix and methods with `test_...`. Favor deterministic
fixtures: temporary directories for SQLite files, fixed datetimes, and explicit
sample connection snapshots. Add coverage for accounting edge cases before
changing delta computation or rollup logic.

## Commit & Pull Request Guidelines

Recent history uses short imperative commit subjects, for example `Add project
brief and MVP status` and `Rename project for Clash Verge traffic ledger`.
Follow that style and keep each commit focused. Pull requests should describe
the behavior change, list the commands run, note any controller or SQLite
manual checks, and include sample report output when CLI formatting changes.

## Security & Configuration Tips

Do not commit local ledgers, secrets, or controller-specific runtime files.
`data/`, `*.sqlite`, and SQLite WAL/SHM files are ignored intentionally. Pass
Mihomo secrets via `--secret` or environment-managed shell variables, not hard
coded defaults.
