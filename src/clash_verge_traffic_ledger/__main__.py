"""Compatibility entry point; prefer python -m clash_verge_monitor."""
from clash_verge_monitor.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
