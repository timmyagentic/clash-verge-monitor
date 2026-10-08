# Output Contract

Machine commands emit one JSON document on stdout, including errors. `--help`
remains human-readable text. Operational stderr is not the result channel.
Legacy human reports (`today`, `status`, `doctor`, `anomalies`, `export`) remain
text commands; use capabilities, health, audit, evidence and explore for agents.
The Skill wrapper also reports argument errors as JSON; bootstrap retains its
argparse usage text for invalid arguments.

```json
{
  "schema_version": "1",
  "runtime": {"name": "clash-verge-traffic-ledger", "version": "0.4.0rc1"},
  "ok": true,
  "operation": "audit",
  "generated_at": "2026-07-19T10:00:00+00:00",
  "data": {},
  "warnings": [],
  "errors": [],
  "next_actions": []
}
```

`ok` means the requested operation completed. Runtime health belongs in `data.status`; a completed health check may be `degraded` while `ok` remains true.

## Exit Codes

- `0`: operation completed, including degraded health or insufficient baseline.
- `1`: operational/install failure.
- `2`: invalid command-line usage (`invalid_arguments`).
- `3`: runtime or database unavailable.
- `4`: invalid data, case, or audit request.

## Audit Cases

Each case includes a deterministic `case_id`, `code`, `severity`, `confidence`, window, typed subject, observed upload/download/total bytes, baseline statistics, ratio, evidence metrics, and limitations. The ID encodes policy/window identity and can be passed to `evidence`; it does not persist a mutable case record.

Treat byte fields as integers. Do not parse human-formatted sizes. Treat `warnings` and `limitations` as part of the result, not optional prose.

Policy version 3 separates traffic anomalies from attribution coverage. An
`unknown_process_ratio` case may be present as a coverage diagnostic, but it
does not by itself change `data.verdict` to `anomalies_detected`.

`data.coverage` includes:

- `latest_sample`, `sample_age_seconds`, and `window_end_status` (`complete`,
  `partial`, or `unknown`), so an Agent can state the actual audit cutoff.
- `process_attribution`, including known/unknown bytes, ratio, thresholds, and
  status.

Current-day audits emit `partial_window_day`; stale or missing samples are
reported separately. Evidence output includes `source_breakdown` and a
`connection_pattern` summary with per-connection byte statistics and repeated
start-minute detection. `periodic_clusters` detects stable timing within each
source address so unrelated localhost traffic does not hide a TUN pattern.

Health output separates `sampling_ready` from `attribution_ready`. A sampler
may be running and fresh while overall health is `degraded` because live process
attribution is below its coverage threshold.

Applied compact maintenance reports `database_bytes_before`,
`database_bytes_after`, and `reclaimed_bytes` in addition to deleted raw rows
and preserved rollup dates.


## Discovery and runtime selection

`capabilities` requires no database and reports commands, grouping/sort values,
limits, coverage and data states, database schema and audit policy versions.
Envelope `schema_version` is independent of `runtime.version`, `policy_version`
and SQLite schema version. Version 1 permits additive fields; ignore unfamiliar
fields. The wrapper adds `runtime_selection` with mode, interpreter, explicit
source (when supplied) and selected database. `runtime_upgrade_required` (exit 3)
means the selected old runtime does not support discovery/the requested command.
Use bootstrap status to inspect that installation or explicitly select source;
do not install, restart, or fall back silently.

## Explore result interpretation

`query` echoes start/end (inclusive), by, process, host, route, limit, offset and
sort, including defaults. Filter strings are exact matches; empty means unfiltered.
Bytes are integer sampled deltas, not billing. `totals` cover all matching retained
rows, while `rows` is only the requested page. `total_groups` counts all matching
groups; `truncated` means there are more groups after this page. Maximum limit is
1000, offset is 0–1000000, and date range is at most 367 days. Invalid bounds fail
rather than being silently clamped. Sort ties use subject ascending.

`data.data_status` has these values:

- `unobserved`: zero retained bytes and unknown sampling coverage.
- `indeterminate_zero`: zero retained bytes, but coverage or retention prevents a zero conclusion.
- `observed_zero`: zero retained sampled bytes, complete coverage and no detected detail deficit.
- `observed_nonzero`: positive retained bytes; coverage may still be partial or unknown.

None guarantees all traffic was captured: polling can miss short connections.
`sampling_coverage_incomplete` is emitted for partial/unknown explore coverage.
`retained_detail_incomplete` means detail totals differ from preserved daily totals.
Retention comparison is **unfiltered** across the requested window, not per-subject
proof; its states are complete/partial/not_applicable (both byte sums are zero).
Keep this separate from sampling coverage. Missing historical heartbeat is unknown,
not zero; a closed day needs >=99% coverage to be complete. Today remains partial.

## Query provenance

Explore, audit and evidence share `query` and `provenance`. Health includes the
actual database/heartbeat plus provenance when readable. Provenance includes:

- `dataset_id`: SHA-256 of the resolved database path; identifies the selected
  location, not immutable contents. Copies get different IDs; replacements at
  the same path retain the ID.
- `database_schema_version`, `latest_sample` (latest retained traffic timestamp),
  `last_success` (sampling heartbeat), `available_rollups`, read timestamps.
- `consistency: live_non_atomic`: the response and later offset pages can span
  concurrent writes. Watermarks are observational, not a snapshot token.
- `timezone`: dates follow recorded local calendar dates, while timestamps carry
  UTC offsets. Do not reinterpret date-only filters as UTC days.

Audit query uses `end_date`, `window_days`, `baseline_days`, `case_limit`. Evidence
query uses `case_id`, `limit`; `live_case_recomputed` warns that evidence recomputes
cases from the current retained database. Case IDs are not persisted snapshots.

## HTTP parity

`/api/capabilities`, `/api/explore`, `/api/audit`, `/api/evidence` use the same
schema-version-1 envelope as CLI, including warnings/errors/runtime. This replaces
the pre-contract raw `/api/explore` and `/api/evidence` response: clients must now
read their payload under `data`. HTML dashboard and CSV export are unchanged.
HTTP audit accepts `end_date` (or `end`), `since`, `baseline`, `limit`; evidence
accepts `case_id`, `limit`; explore accepts the CLI query names without `--`.

API errors are JSON: 400 invalid request/case, 403 forbidden Host/Origin, 404
unknown endpoint, 503 unavailable resource, 500 unexpected failure. Unsupported
HTTP methods remain 501 but have a JSON error envelope. Core CLI equivalents use
exit 4, 3, 1 respectively. Stable error codes include `database_missing`,
`invalid_request`, `case_not_found`, `resource_unavailable`, `invalid_database`,
`operation_failed`. Clients should branch on code, not exception type/message.
