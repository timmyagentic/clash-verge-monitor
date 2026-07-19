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
