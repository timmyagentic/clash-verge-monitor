# Implementation Plan

## Project setup

- Create a Python stdlib-only CLI project named `mihomo-flow-ledger`.
- Keep source under `src/mihomo_flow_ledger`.
- Keep tests under `tests`.
- Initialize a local git repository.

## Tests first

- Test API connection item parsing and process fallback priority.
- Test `lsof` parser output handling.
- Test delta computation:
  - first sample is baseline only
  - second sample records positive deltas
  - disappeared connections are removed
  - negative deltas are skipped
- Test SQLite insertion and daily rollups.
- Test Markdown/CSV report formatting.

## Implementation

- Implement controller client for Unix socket and HTTP mode.
- Implement connection and delta models.
- Implement process lookup through `lsof`.
- Implement SQLite store.
- Implement sampler loop.
- Implement CLI commands: `doctor`, `run`, `today`, `export`.

## Verification

- Run the full unit test suite.
- Run `doctor` against `/tmp/verge/verge-mihomo.sock`.
- Run a short sampler against the live socket and verify the database/report path.
- Commit the resulting repo.

