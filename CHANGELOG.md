# Changelog

All notable project changes are recorded here. A section marked `Unreleased`
is a release candidate, not evidence of a Git tag, GitHub Release, or deployed
runtime.

## [0.3.2] - 2026-10-24

### Added

- Rename the product, Python distribution/module, CLI, Agent Skill and dashboard to Clash Verge Monitor.
- Keep the legacy CLI/module usable, reuse existing installation roots and service identities, and preserve the installed database path when upgrading.
- Prepare the renamed website domain and permanent redirects from the previous website. Published v0.3.1 assets retain their original names.

- Refresh the product website with the timmyagentic visual style while preserving installation, download and documentation paths.

## [0.3.1] - 2026-10-20

### Added

- CI across macOS/Linux and Python 3.11/3.14, distribution install checks, protected PR merges, immutable release tags and a verified tag-to-Release workflow.

- Add the public product website with release-aware setup, local-data boundaries and deployment configuration.

- Shared Agent query envelopes across CLI and HTTP, including runtime capabilities,
  query echo, dataset provenance, explicit zero/unknown data states and coverage warnings.
- Skill exploration, explicit source selection and actionable legacy-runtime errors.
- JSON argument/operation errors on stdout; HTTP API clients now read results under `data`.
- Light overview dashboard with local charts, process rankings, traffic destinations and history.

- Discover current-user Clash sockets and reconnect automatically in auto mode.
- Track successful idle polls, coverage, failures, reset events and core-counter gaps.
- Prevent concurrent samplers and reset baselines after outages, wake gaps and core resets.
- Add transactional schema v2 migrations, hourly route aggregates and safe backup/restore.
- Add filtered minute/connection/rule/chain exploration, CSV and local dashboard diagnostics.
- Policy v3 treats unknown/partial coverage as provisional and never infers full days from traffic dates.
- Configurable preview-first retention preserves daily and hourly summaries.

### Release and compatibility

- Publish the previously untagged `0.4.0rc1` work as `0.3.1`; no `0.4` stable release exists. Future stable releases advance one patch within the current release line.
- Preserve schema v2 and existing raw, daily, hourly and heartbeat history when updating an existing candidate installation. Upgrading from `0.3.0` adds schema v2 tables after a guarded backup; it does not delete history.
- Agent HTTP results are under `data`; CLI/HTTP query responses include coverage, provenance and explicit unknown/zero states. Consumers of the old HTTP shape must use the documented envelope.
- Close test SQLite connections explicitly to remove ResourceWarning noise.
- Report launchd status as unavailable when `launchctl` is absent, so portable reporting and non-loaded bootstrap inspection work on Linux.

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
