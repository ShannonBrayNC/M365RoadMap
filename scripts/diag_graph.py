#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

# Windows console safe
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

# --- Robust imports: prefer sibling file, then package ---
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
try:
    # Same-folder import (always works when running this file)
    from graph_client import GraphConfig, GraphClient  # type: ignore
except Exception:
    # If you run from repo root and have scripts/ as a package
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.graph_client import GraphConfig, GraphClient  # type: ignore


def resolve_config(path_arg: str | None) -> tuple[GraphConfig, str]:
    """Use --config if given; else graph_config.json if present; else env."""
    if path_arg:
        p = Path(path_arg)
        if not p.exists():
            raise FileNotFoundError(f"--config '{path_arg}' not found")
        return GraphConfig.from_file(str(p)), f"file:{p.resolve()}"
    default = _REPO_ROOT / "graph_config.json"
    if default.exists():
        return GraphConfig.from_file(str(default)), f"file:{default}"
    return GraphConfig.from_env(), "env"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sanity-check Microsoft Graph Message Center access.")
    ap.add_argument("--config", help="Path to graph_config.json (auto-used if present)")
    ap.add_argument("--top", type=int, default=10, help="How many MC items to read (default: 10, max 100)")
    ap.add_argument("--days", type=int, default=365, help="Look back this many days (default: 365)")
    args = ap.parse_args(argv)

    try:
        cfg, mode = resolve_config(args.config)
        print(f"[diag] Config mode: {mode}")
        print(f"[diag] Graph base : {cfg.graph_base}")
        print(f"[diag] Authority  : {cfg.authority_base}/{cfg.tenant_id}")

        cli = GraphClient(cfg)
        lookback = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(1, args.days))
        print(f"[diag] Fetching up to {min(max(args.top,1),100)} items "
              f"modified since {lookback.isoformat()} ...\n")

        seen = 0
        for m in cli.iter_service_messages(top=min(max(args.top,1),100), last_modified_ge=lookback):
            mid = m.get("id", "")
            title = (m.get("title") or "").strip()
            lm = (m.get("lastModifiedDateTime") or "").strip()
            services = ", ".join(m.get("services", []) or [])
            print(f"- {mid}  [{lm}]  {title}")
            if services:
                print(f"    services: {services}")
            seen += 1

        print(f"\n[diag] graph_messages: {seen}")
        if seen == 0:
            print(
                "[diag] No items returned. Check:\n"
                "  • App permission: ServiceMessage.Read.All (Application) with admin consent\n"
                "  • PFX password env present (M365_PFX_PASSWORD)\n"
                "  • Tenant/client IDs (GUIDs or valid domain)\n"
                "  • Sovereign endpoints (GRAPH_BASE / AUTHORITY_BASE) if applicable",
                file=sys.stderr,
            )
        return 0
    except Exception as e:
        print(f"[diag] ERROR: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
