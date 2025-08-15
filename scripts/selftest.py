#!/usr/bin/env python3
"""
selftest.py — smoke-test the three data paths

- Graph Message Center (primary)
- Public Roadmap via Playwright (optional; skipped if not installed or --no-public-scrape)
- Public RSS/JSON API fallback

Usage examples:
  # Quick check with Graph only (needs graph_config.json + env password)
  python scripts/selftest.py --months 1

  # Graph + RSS for two roadmap ids
  python scripts/selftest.py --months 1 --ids 498159,499430

  # Skip Graph, try Playwright (if installed) and RSS:
  python scripts/selftest.py --no-graph --ids 498159,499430

Exit code is 0 on success (at least one method produced rows), 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

# --- Local imports from your repo ---
try:
    from graph_client import acquire_token
except Exception:
    acquire_token = None

try:
    from fetch_messages_graph import TABLE_HEADERS, list_messages, map_mc_to_row
except Exception as e:
    print("[selftest] Could not import fetch_messages_graph pieces:", e, file=sys.stderr)
    sys.exit(1)

# Optional Playwright-based fallback
PLAYWRIGHT_OK = True
try:
    from fallback_public_roadmap import fetch_ids_public
except Exception:
    PLAYWRIGHT_OK = False

from fallback_rss_api import fetch_ids_rss


def iso_utc_start_of_day(d: datetime) -> str:
    return d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC).isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="graph_config.json", help="Graph config json")
    ap.add_argument("--months", default="", help="1..6; compute since=UTC-now-(n months)")
    ap.add_argument("--since", default="", help="YYYY-MM-DD (used if months not set)")
    ap.add_argument("--tenant-cloud", default="Worldwide (Standard Multi-Tenant)")
    ap.add_argument("--ids", default="", help="Comma-separated Roadmap IDs for public fallbacks")
    ap.add_argument("--no-graph", action="store_true", help="Skip Graph check")
    ap.add_argument(
        "--no-public-scrape", action="store_true", help="Skip Playwright even if installed"
    )
    ap.add_argument(
        "--samples", type=int, default=2, help="How many sample rows to display per method"
    )
    args = ap.parse_args()

    # Compute since
    since_iso = None
    if args.months:
        try:
            n = int(args.months)
            if 1 <= n <= 6:
                since_dt = datetime.utcnow().replace(tzinfo=UTC) - timedelta(days=int(30.44 * n))
                since_iso = iso_utc_start_of_day(since_dt)
        except Exception:
            pass
    if args.since and not since_iso:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC)
            since_iso = iso_utc_start_of_day(since_dt)
        except Exception:
            pass

    id_list = [s.strip() for s in args.ids.split(",") if s.strip()]
    overall_rows = 0

    print("=== Self-test: configuration ===")
    print(f"  Graph: {'ENABLED' if not args.no-graph else 'DISABLED'}  | config: {args.config}")
    print(
        f"  Public scrape (Playwright): {'ENABLED' if (PLAYWRIGHT_OK and not args.no_public_scrape) else 'DISABLED'} (installed={PLAYWRIGHT_OK})"
    )
    print("  RSS/JSON fallback: ENABLED")
    print(f"  IDs: {id_list if id_list else '(none given)'}")
    print(f"  Since: {since_iso or '(not set)'}")
    print()

    # ---- Graph path ----
    graph_rows = []
    graph_err = None
    if not args.no_graph:
        try:
            with open(args.config, encoding="utf-8") as f:
                cfg = json.load(f)
            if acquire_token is None:
                raise RuntimeError("graph_client.acquire_token unavailable")
            token = acquire_token(cfg)
            print("[graph] token acquired OK.")
            for i, msg in enumerate(list_messages(cfg["graph_base"], token, since_iso=since_iso)):
                graph_rows.append(map_mc_to_row(msg, tenant_cloud_hint=args.tenant_cloud))
                if i >= 500:  # cap in self-test
                    break
        except Exception as e:
            graph_err = e
            print(f"[graph] FAILED: {e}", file=sys.stderr)

    # ---- Public/Playwright path ----
    public_rows = []
    if id_list and PLAYWRIGHT_OK and not args.no_public_scrape:
        try:
            public_rows = fetch_ids_public(id_list)
        except Exception as e:
            print(f"[public] FAILED: {e}", file=sys.stderr)

    # ---- RSS/JSON fallback path ----
    rss_rows = []
    if id_list:
        try:
            # For any ids not found via public scrape, the fetcher does selective remainder;
            # in self-test, just call for all provided ids to confirm the API path works.
            rss_rows = fetch_ids_rss(id_list)
        except Exception as e:
            print(f"[rss] FAILED: {e}", file=sys.stderr)

    # ---- Summaries ----
    print("\n=== Results ===")
    print(
        f"[rows] Graph={len(graph_rows)} Public={len(public_rows)} RSS={len(rss_rows)} Total={len(graph_rows)+len(public_rows)+len(rss_rows)}\n"
    )

    def show_samples(label, rows):
        print(f"-- {label} sample rows (up to {args.samples}) --")
        if not rows:
            print("  (no rows)")
            return
        print("  " + " | ".join(TABLE_HEADERS))
        for r in rows[: args.samples]:
            safe = [str(x) if x is not None else "" for x in r]
            print("  " + " | ".join(safe))
        print()

    show_samples("Graph", graph_rows)
    show_samples("Public", public_rows)
    show_samples("RSS", rss_rows)

    overall_rows = len(graph_rows) + len(public_rows) + len(rss_rows)
    if overall_rows == 0:
        print(
            "Self-test produced no rows. Check credentials, secrets, or provide --ids.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Self-test OK.")
    sys.exit(0)


if __name__ == "__main__":
    main()
