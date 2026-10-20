#!/usr/bin/env python3
"""Install the built wheel in an isolated environment and check its CLI/assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv

from check_release import distribution_errors, project_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--write-checksums", action="store_true")
    args = parser.parse_args()
    version = project_version()
    dist = args.dist_dir.resolve()
    errors = distribution_errors(dist, version)
    if errors:
        raise SystemExit("\n".join(errors))
    wheel = dist / f"clash_verge_traffic_ledger-{version}-py3-none-any.whl"
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        venv.create(root / "venv", with_pip=True)
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
                       cwd=root, env=environment, check=True)
        output = subprocess.check_output([str(python), "-I", "-m", "clash_verge_traffic_ledger",
                                          "capabilities"], cwd=root, env=environment, text=True)
        result = json.loads(output)
        if not result["ok"] or result["runtime"]["version"] != version:
            raise SystemExit("installed wheel capabilities/version mismatch")
        subprocess.run([str(python), "-I", "-m", "clash_verge_traffic_ledger", "--help"],
                       cwd=root, env=environment, check=True, stdout=subprocess.DEVNULL)
    if args.write_checksums:
        artifacts = [wheel, dist / f"clash_verge_traffic_ledger-{version}.tar.gz"]
        (dist / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts))
    print(f"Distribution install smoke OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
