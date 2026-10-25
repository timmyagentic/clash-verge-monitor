# Contributing

Use Python 3.11 or newer. The runtime has no third-party dependencies; build/CI tools are pinned in `requirements-dev.txt`.

```sh
python3 -m pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/check_repository_policy.py --allow-dirty
git diff --check
```

Main requires a PR, an up-to-date branch, resolved discussions, and the two GitHub Actions checks (Linux checks and macOS checks) in `.github/main-ruleset.json`. Linux uses Python 3.11 for policy, tests and wheel/sdist installation checks; macOS uses Python 3.14 for tests and real launchd acceptance. External Actions use full commit SHAs and default permissions are read-only.

This single-maintainer repository does not require a second human approval, which its author could not provide. PR/CI/discussion gates apply to administrators too; the ruleset has no bypass actors. Review the final diff and checks for the exact PR head, then use squash merge with `gh pr merge --squash --match-head-commit <sha>`. Do not use `--admin` or direct main pushes.

Stable versions advance one patch within the current line. `0.3.1` includes the former unpublished `0.4.0rc1` candidate; it does not require a schema downgrade. Historical validation records keep their original version labels. Future stable releases are `0.3.2`, `0.3.3`, and so on. Do not retag or overwrite published assets.

[The release process](docs/releasing.md) separates source/CI, tag/Release and local installation acceptance. Maintenance and live-controller tests always use temporary data unless explicitly authorized. Never prune, compact, reset or rewrite real history as part of a software release.

## Merge and branch cleanup

Follow [the repository workflow](AGENTS.md#repository-workflow-and-branch-protection): default-branch changes require a PR and squash merging, with resolved review conversations and no administrator bypass. Keep automatic remote-branch deletion enabled. Local branches and worktrees remain for the existing Tingjun Workspace archive workflow; do not use `--delete-branch` during merge. The minimal CI checks are documented in AGENTS.md and declared in .github/main-ruleset.json.
