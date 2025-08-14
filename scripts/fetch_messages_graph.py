#!/usr/bin/env python3
"""
fetch_messages_graph.py — primary: Microsoft Graph Message Center
fallbacks: (optional) public Roadmap by ID (Playwright) -> RSS/JSON API by ID

Emits your master table CSV/JSON headers:
| ID | Title | Product/Workload | Status | Release phase | Targeted dates | Cloud instance | Short description | Official Roadmap link |
"""
import argparse, csv, json, os, sys
from datetime import datetime, timedelta, timezone
from typing import List, Set
import requests

from graph_client import acquire_token
from fallback_rss_api import fetch_ids_rss

# Optional Playwright-based fallback (only if installed AND not disabled)
PLAYWRIGHT_OK = True
try:
    from fallback_public_roadmap import fetch_ids_public  # imports playwright
except Exception:
    PLAYWRIGHT_OK = False

TABLE_HEADERS = [
    "ID","Title","Product/Workload","Status","Release phase",
    "Targeted dates","Cloud instance","Short description","Official Roadmap link"
]

def iso_utc_start_of_day(d: datetime) -> str:
    return d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc).isoformat()

def to_list(x):
    if isinstance(x, list): return x
    if x is None: return []
    return [x]

def clean_text(s):
    if not isinstance(s, str): return s
    return " ".join(s.replace("\u200b", "").replace("|"," / ").split())

def discover_official_link(details, body_html):
    import re
    links = []
    if isinstance(details, list):
        for d in details:
            if isinstance(d, dict):
                v = d.get("value") or d.get("url") or d.get("link")
                if v: links.append(v)
            elif isinstance(d, str):
                links.append(d)
    if isinstance(body_html, str):
        for m in re.finditer(r'href="([^"]+)"', body_html, re.I):
            links.append(m.group(1))
    roadmap = next((L for L in links if isinstance(L,str) and "microsoft-365/roadmap?featureid=" in L.lower()), None)
    official = next((L for L in links if isinstance(L,str) and ("learn.microsoft.com" in L or "support.microsoft.com" in L or "microsoft.com" in L)), None)
    return roadmap or official or ""

def map_mc_to_row(msg: dict, tenant_cloud_hint: str = ""):
    mcid = clean_text(msg.get("id",""))
    title = clean_text(msg.get("title",""))
    services = clean_text(", ".join(to_list(msg.get("services"))))
    status = ""  # MC schema doesn't map to Roadmap Status
    phase  = ""  # MC schema doesn't map to Roadmap Release phase
    targeted = ""
    for k in ("startDateTime","actionRequiredByDateTime","lastModifiedDateTime","endDateTime"):
        if msg.get(k):
            targeted = clean_text(msg[k]); break
    cloud_instance = clean_text(tenant_cloud_hint or "")
    tags_part = ", ".join(to_list(msg.get("tags")))
    short_desc = clean_text("; ".join([v for v in [msg.get("category",""), tags_part] if v]))
    official_link = discover_official_link(msg.get("details"), (msg.get("body") or {}).get("content"))
    return [mcid, title, services, status, phase, targeted, cloud_instance, short_desc, official_link]

def list_messages(graph_base: str, token: str, since_iso: str | None):
    url = f"{graph_base.rstrip('/')}/admin/serviceAnnouncement/messages"
    params = {}
    if since_iso:
        params["$filter"] = f"lastModifiedDateTime ge {since_iso}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Prefer": "odata.maxpagesize=1000"}
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        for m in data.get("value", []):
            yield m
        url = data.get("@odata.nextLink")
        params = None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="graph_config.json")
    ap.add_argument("--months", default="", help="1..6; compute since=UTC-now-(n months)")
    ap.add_argument("--since", default="", help="YYYY-MM-DD (used if months not set)")
    ap.add_argument("--tenant-cloud", default="", help='Cloud instance label for Graph rows')
    ap.add_argument("--emit", choices=["csv","json"], default="csv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ids", default="", help="Comma-separated public Roadmap feature IDs for fallback/merge")
    ap.add_argument("--no-graph", action="store_true", help="Skip Graph and use public fallbacks only (requires --ids)")
    ap.add_argument("--no-public-scrape", action="store_true", help="Skip Playwright scraping even if installed")
    ap.add_argument("--stats-out", default="", help="Optional path to write a JSON summary of method counts")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    # compute since
    since_iso = None
    if args.months:
        try:
            n = int(args.months)
            if 1 <= n <= 6:
                since_dt = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=int(30.44*n))
                since_iso = iso_utc_start_of_day(since_dt)
        except Exception:
            pass
    if args.since and not since_iso:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            since_iso = iso_utc_start_of_day(since_dt)
        except Exception:
            pass

    rows: List[List[str]] = []
    graph_error = None

    # per-method counters
    graph_cnt = 0
    public_cnt = 0
    rss_cnt = 0

    # 1) Graph (primary)
    if not args.no_graph:
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            token = acquire_token(cfg)
            for msg in list_messages(cfg["graph_base"], token, since_iso=since_iso):
                rows.append(map_mc_to_row(msg, tenant_cloud_hint=args.tenant_cloud))
                graph_cnt += 1
            if args.debug:
                print(f"[fetch] Graph fetched {graph_cnt} messages", file=sys.stderr)
        except Exception as e:
            graph_error = e
            if args.debug:
                print(f"[fetch] Graph failed: {e}", file=sys.stderr)

    # 2) Public IDs (Playwright) if provided AND allowed AND playwright is available
    id_list = [s.strip() for s in args.ids.split(",") if s.strip()]
    fetched_ids: Set[str] = set()
    if id_list and not args.no_public_scrape and PLAYWRIGHT_OK:
        try:
            pub_rows = fetch_ids_public(id_list)
            for r in pub_rows:
                if r and r[0]:
                    fetched_ids.add(r[0])
            rows.extend(pub_rows)
            public_cnt += len(pub_rows)
            if args.debug:
                print(f"[fetch] Public fallback (Playwright) fetched {len(pub_rows)} rows", file=sys.stderr)
        except Exception as e:
            if args.debug:
                print(f"[fetch] Public fallback (Playwright) failed: {e}", file=sys.stderr)
    elif id_list and (args.no_public_scrape or not PLAYWRIGHT_OK) and args.debug:
        why = "disabled via --no-public-scrape" if args.no_public_scrape else "playwright not installed"
        print(f"[fetch] Skipping Playwright fallback ({why}); trying RSS/JSON for IDs.", file=sys.stderr)

    # 3) RSS/JSON API fallback for any remaining IDs
    remaining = [i for i in id_list if i not in fetched_ids]
    if remaining:
        try:
            rss_rows = fetch_ids_rss(remaining)
            rows.extend(rss_rows)
            rss_cnt += len(rss_rows)
            if args.debug:
                print(f"[fetch] RSS/JSON fallback fetched {len(rss_rows)} rows for remaining IDs", file=sys.stderr)
        except Exception as e:
            if args.debug:
                print(f"[fetch] RSS/JSON fallback failed: {e}", file=sys.stderr)

    if not rows:
        msg = "No rows produced. "
        if graph_error:
            msg += f"Graph error: {graph_error}. "
        if not id_list:
            msg += "No public IDs supplied for fallbacks."
        raise SystemExit(msg)

    # Write output data
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if args.emit == "csv":
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(TABLE_HEADERS)
            w.writerows(rows)
    else:
        dicts = [dict(zip(TABLE_HEADERS, r)) for r in rows]
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(dicts, f, ensure_ascii=False, indent=2)

    total = len(rows)
    summary_line = f"[rows] Graph={graph_cnt} Public={public_cnt} RSS={rss_cnt} Total={total}"
    print(summary_line)

    if args.stats_out:
        stats = {"graph": graph_cnt, "public": public_cnt, "rss": rss_cnt, "total": total}
        os.makedirs(os.path.dirname(args.stats_out) or ".", exist_ok=True)
        with open(args.stats_out, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
