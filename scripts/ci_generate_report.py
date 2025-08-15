#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import subprocess
import sys


def _truthy(s: str | None) -> bool:
    if s is None:
        return False
    return s.strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    title = os.environ.get("TITLE")  # optional convenience, but we pass via CLI below
    # required via CLI args from action:
    #   --title, --master, --out
    # We just forward those; we only add optional flags from env.

    # Build argv safely (no heredocs, no shell conditionals).
    argv: list[str] = [sys.executable, "-m", "scripts.generate_report"]

    # The action passes required args on CLI; keep them first
    # NOTE: we pick them from sys.argv to keep this wrapper generic.
    # Expected: ci_generate_report.py --title <t> --master <m> --out <o>
    it = iter(sys.argv[1:])
    for flag in it:
        argv.append(flag)
        if not flag.startswith("--"):
            continue
        # flags we use all take a value
        if flag in {"--title", "--master", "--out"}:
            try:
                argv.append(next(it))
            except StopIteration:
                print(f"Missing value for {flag}", file=sys.stderr)
                sys.exit(2)

    # Optional banner info from env:
    since = os.environ.get("SINCE", "")
    months = os.environ.get("MONTHS", "")
    no_window = _truthy(os.environ.get("NO_WINDOW"))

    if no_window:
        argv.append("--no-window")
    if since:
        argv.extend(["--since", since])
    if months:
        argv.extend(["--months", months])

    # Cloud checkboxes → banner clouds
    if _truthy(os.environ.get("CLOUD_GENERAL", "true")):
        argv.extend(["--cloud", "Worldwide (Standard Multi-Tenant)"])
    if _truthy(os.environ.get("CLOUD_GCC", "false")):
        argv.extend(["--cloud", "GCC"])
    if _truthy(os.environ.get("CLOUD_GCCH", "false")):
        argv.extend(["--cloud", "GCC High"])
    if _truthy(os.environ.get("CLOUD_DOD", "false")):
        argv.extend(["--cloud", "DoD"])

    forced_ids = os.environ.get("PUBLIC_IDS", "")
    if forced_ids:
        argv.extend(["--forced-ids", forced_ids])

    print("ci_generate_report.py invoking:")
    print("  " + " ".join(shlex.quote(a) for a in argv))

    # Exec the real generator
    res = subprocess.run(argv)
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()
