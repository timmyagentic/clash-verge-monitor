# Changelog

All notable project changes are recorded here. A section marked `Unreleased`
is a release candidate, not evidence of a Git tag, GitHub Release, or deployed
runtime.

## [0.4.0rc1] - Unreleased

### Added

- Discover current-user Clash sockets and reconnect automatically in auto mode.
- Track successful idle polls, coverage, failures, reset events and core-counter gaps.
- Prevent concurrent samplers and reset baselines after outages, wake gaps and core resets.
- Add transactional schema v2 migrations, hourly route aggregates and safe backup/restore.
- Add filtered minute/connection/rule/chain exploration, CSV and local dashboard diagnostics.
- Policy v3 treats unknown/partial coverage as provisional and never infers full days from traffic dates.
- Configurable preview-first retention preserves daily and hourly summaries.

## [0.3.0] - 2026-08-15

### Added

- TUN and UDP process attribution from a single batched local socket snapshot.
- Separate sampling and attribution readiness in health output.
- Source-address, per-connection, and periodic-cluster evidence for audit cases.
- Current-day cutoff and sample-freshness metadata in deterministic audit output.
- SQLite compaction reporting with `VACUUM` byte reclamation.
- Release metadata, artifact-content, clean-source, and version/tag gates.

### Changed

- Upgraded anomaly decisions to policy version 2.
- Treat chronic `unknown` traffic as an attribution coverage diagnostic instead
  of escalating it as a standalone security or traffic verdict.
- Reuse the last known process only for the lifetime of the same connection.
- Correct the polling cadence by subtracting work time from the requested
  sampling interval.
- Report untracked source files in installed-runtime provenance.

### Fixed

- Keep rollup freshness timestamps monotonic when deltas are written out of
  order, including after raw evidence is compacted.
- Treat malformed or literal `unknown` process metadata as an attribution gap
  instead of failing the whole controller snapshot.

### Safety

- All raw-retention commands remain a dry run until `--apply` is explicit, and
  reject cutoffs that are not exact `YYYY-MM-DD` dates before deleting rows.
- High volume, periodic traffic, and unknown attribution remain evidence to
  inspect; none is treated as proof of malicious behavior.

## [0.2.0] - 2026-07-19

- Added the Skill-first deterministic health, audit, evidence, maintenance, and
  stable-runtime bootstrap workflow.
- Added launchd sampler and read-only Web service installation.

## [0.1.0] - 2026-07-02

- Added the initial Mihomo connection sampler, SQLite ledger, process/host
  rollups, reports, and local CLI.
