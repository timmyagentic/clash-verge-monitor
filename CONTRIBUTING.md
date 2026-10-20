# Contributing

Use Python 3.11 or newer. The runtime has no third-party dependencies; build/CI tools are pinned in `requirements-dev.txt`.

```sh
python3 -m pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -B -W error::ResourceWarning -m unittest discover -s tests -v
python3 scripts/check_repository_policy.py --allow-dirty
git diff --check
```

Main requires a PR, an up-to-date branch, resolved discussions, and the six GitHub Actions checks in `.github/main-ruleset.json`. Tests run on macOS/Linux with Python 3.11/3.14; Distribution builds and checks wheel/sdist contents and installs the wheel in a fresh environment. External Actions use full commit SHAs and default permissions are read-only.

This single-maintainer repository does not require a second human approval, which its author could not provide. PR/CI/discussion gates apply to administrators too; the ruleset has no bypass actors. Review the final diff and checks for the exact PR head, then use squash merge with `gh pr merge --squash --match-head-commit <sha>`. Do not use `--admin` or direct main pushes.

Stable versions advance one patch within the current line. `0.3.1` includes the former unpublished `0.4.0rc1` candidate; it does not require a schema downgrade. Historical validation records keep their original version labels. Future stable releases are `0.3.2`, `0.3.3`, and so on. Do not retag or overwrite published assets.

[The release process](docs/releasing.md) separates source/CI, tag/Release and local installation acceptance. Maintenance and live-controller tests always use temporary data unless explicitly authorized. Never prune, compact, reset or rewrite real history as part of a software release.
