# Troubleshooting

## Runtime Not Installed

Run `bootstrap.py status`. From a project-local skill, pass the repository root with `bootstrap.py install --source <repo>`. A copied standalone Skill still needs access to a matching repository source or release artifact; do not download arbitrary code or guess a source.

## Controller Unreachable

The default Clash Verge socket is `/tmp/verge/verge-mihomo.sock`. Start Clash Verge and rerun health. Historical audit can continue when `audit_ready` is true even if live sampling is unavailable.

## Stale Samples

Compare `database.latest_sample`, `database.sample_age_seconds`, sampler state, and controller reachability. The sampler now retries transient socket and timeout errors with bounded exponential backoff. Inspect the stable `logs/sampler.err.log` before restarting it.

## SQLite Busy Or Locked

Audit opens SQLite in `mode=ro`, enables query-only mode, and waits up to 30 seconds for a busy writer. Retry only after reading the error and confirming the sampler is making progress. Do not stop the sampler or copy the 1 GB database merely to hide a repeated locking problem.

## Insufficient Baseline

Report `active_baseline_days` and continue collecting data. Absolute volume and unknown-attribution cases may still be reported, but robust change conclusions remain low confidence.

## Secret Handling

Use `MIHOMO_SECRET` for an interactive process. For launchd, create a user-only file with `chmod 600` and pass only `--secret-file <path>`. Never echo the secret or place its contents in JSON, plist arguments, or logs.
