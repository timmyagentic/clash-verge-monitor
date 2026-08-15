# Output Contract

All Agent-facing scripts emit one JSON document on stdout.

```json
{
  "schema_version": "1",
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
- `2`: invalid command-line usage from `argparse`.
- `3`: runtime or database unavailable.
- `4`: invalid data, case, or audit request.

## Audit Cases

Each case includes a deterministic `case_id`, `code`, `severity`, `confidence`, window, typed subject, observed upload/download/total bytes, baseline statistics, ratio, evidence metrics, and limitations. The ID encodes policy/window identity and can be passed to `evidence`; it does not persist a mutable case record.

Treat byte fields as integers. Do not parse human-formatted sizes. Treat `warnings` and `limitations` as part of the result, not optional prose.

Policy version 2 separates traffic anomalies from attribution coverage. An
`unknown_process_ratio` case may be present as a coverage diagnostic, but it
does not by itself change `data.verdict` to `anomalies_detected`.

`data.coverage` includes:

- `latest_sample`, `sample_age_seconds`, and `window_end_status` (`complete`,
  `partial`, or `missing`), so an Agent can state the actual audit cutoff.
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
