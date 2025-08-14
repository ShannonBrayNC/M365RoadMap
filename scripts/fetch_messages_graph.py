# -*- coding: utf-8 -*-
"""
fetch_messages_graph.py
End-to-end discovery of Roadmap IDs from (in priority order):
  1) Microsoft Graph: admin/serviceAnnouncement/messages
  2) Public Roadmap JSON (download-all, then filter by id or cloud text)
  3) Public Roadmap RSS (as a last resort)

Then emits results as CSV / JSON / list, and writes a one-line stats file.

USAGE (examples)
---------------
# Last 3 months, Worldwide, emit CSV and stats
python scripts/fetch_messages_graph.py \
  --config graph_config.json \
  --months 3 \
  --tenant-cloud "Worldwide (Standard Multi-Tenant)" \
  --emit csv --out output/graph_messages_master.csv \
  --stats-out output/fetch_stats.json --debug

# Use explicit ids (skip discovery), just format output
python scripts/fetch_messages_graph.py \
  --ids "498159,369345" --emit csv --out output/ids.csv

# JSON output instead of CSV
python scripts/fetch_messages_graph.py \
  --config graph_config.json --months 3 --emit json --out output/master.json
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

# Optional but recommended (already in your repo's requirements.txt)
from bs4 import BeautifulSoup  # type: ignore
import feedparser  # type: ignore

# Local helper (your working version)
# Provides: acquire_token(config) -> str  and  graph_get_json(url, token) -> dict
from scripts.graph_client import acquire_token, graph_get_json  # type: ignore


PUBLIC_ROADMAP_JSON = "https://www.microsoft.com/releasecommunications/api/v2/m365/roadmap"
PUBLIC_ROADMAP_RSS = "https://www.microsoft.com/releasecommunications/api/v2/m365/rss"

ROADMAP_LINK_FMT = "https://www.microsoft.com/microsoft-365/roadmap?featureid={id}"

ID_RE = re.compile(r"\b(\d{3,6})\b")
CLOUD_LABELS = [
    "Worldwide (Standard Multi-Tenant)",
    "GCC",
    "GCC High",
    "DoD",
    # common alternates we may see in prose
    "Worldwide",
    "General Availability (Worldwide)",
    "Government Community Cloud (GCC)",
    "Government Community Cloud High  (GCC High)",
    "Department of Defense (DoD)",
]


def _debug_print(enabled: bool, *args: Any) -> None:
    if enabled:
        print(*args)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="graph_config.json (tenant/client/pfx...)", default=None)
    p.add_argument("--months", type=int, default=None, help="Window in months back from today")
    p.add_argument("--since", default=None, help="ISO date YYYY-MM-DD (start)")
    p.add_argument("--until", default=None, help="ISO date YYYY-MM-DD (end)")
    p.add_argument("--tenant-cloud", default=None, help="Filter by cloud/tenant label (e.g., 'GCC High')")
    p.add_argument("--ids", default=None, help="Explicit comma-separated roadmap IDs (bypass discovery)")

    p.add_argument("--emit", choices=["csv", "json", "list"], required=True)
    p.add_argument("--out", default=None, help="Output file path (required for csv/json)")

    p.add_argument("--stats-out", default=None, help="Write per-source counts to this JSON path")

    p.add_argument("--no-graph", action="store_true", help="Disable Graph source")
    p.add_argument("--no-public-scrape", action="store_true", help="Disable public JSON/RSS fallbacks")
    p.add_argument("--max-pages", type=int, default=30, help="(kept for compatibility) not used by Graph; we page until nextLink ends")

    p.add_argument("--debug", action="store_true")
    return p.parse_args(argv)


def today_utc() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)


def parse_iso_d(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc) if "T" not in s else dt.datetime.fromisoformat(s)


def compute_range(months: Optional[int], since: Optional[str], until: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    if since or until:
        return parse_iso_d(since), parse_iso_d(until)
    if months:
        end = today_utc()
        start = end - dt.timedelta(days=int(months * 30.5))
        return start, end
    return None, None


def in_range(ts: Optional[str], start: Optional[dt.datetime], end: Optional[dt.datetime]) -> bool:
    if not (start or end):
        return True
    if not ts:
        return False
    try:
        # Graph uses full ISO with Z
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return False
    if start and t < start:
        return False
    if end and t > end:
        return False
    return True


def cloud_matches(text: str, desired: Optional[str]) -> bool:
    if not desired:
        return True
    return desired.lower() in text.lower()


# ---------------------------
# GRAPH
# ---------------------------

def fetch_graph_messages(config: Dict[str, Any], debug: bool) -> List[Dict[str, Any]]:
    """
    Fetch ALL pages from Graph admin/serviceAnnouncement/messages
    Returns a list of raw message objects.
    """
    token = acquire_token(config)
    base = (config.get("graph_base") or "https://graph.microsoft.com/v1.0").rstrip("/")
    url = f"{base}/admin/serviceAnnouncement/messages?$top=100"

    out: List[Dict[str, Any]] = []
    while url:
        page = graph_get_json(url, token)
        vals = page.get("value", [])
        if not isinstance(vals, list):
            break
        out.extend(vals)
        _debug_print(debug, f"[graph] got {len(vals)} (cum {len(out)})")
        url = page.get("@odata.nextLink")
    return out


def extract_roadmap_from_graph(messages: List[Dict[str, Any]],
                               date_start: Optional[dt.datetime],
                               date_end: Optional[dt.datetime],
                               tenant_cloud: Optional[str],
                               debug: bool) -> List[Dict[str, Any]]:
    """
    Convert Graph message objects into rows keyed by Roadmap ID.
    Returns rows: {"id","title","status","phase","targeted_dates","cloud_instances","link","source"}
    """
    rows: Dict[str, Dict[str, Any]] = {}  # by roadmap id

    for m in messages:
        last_mod = m.get("lastModifiedDateTime") or m.get("startDateTime")
        if not in_range(last_mod, date_start, date_end):
            continue

        body_html = ((m.get("body") or {}).get("content") or "")
        if tenant_cloud and body_html:
            if not cloud_matches(body_html, tenant_cloud):
                # Try also cloud labels list
                if not any(cloud_matches(body_html, lbl) and cloud_matches(lbl, tenant_cloud) for lbl in CLOUD_LABELS):
                    continue

        # Pull roadmap ids from details or from the HTML body as fallback
        rm_ids: List[str] = []
        for d in m.get("details", []):
            if d.get("name") == "RoadmapIds" and d.get("value"):
                rm_ids.extend([x.strip() for x in d["value"].split(",") if x.strip()])

        if not rm_ids and body_html:
            # Fallback: look for "... Roadmap ID 369345 ..." or links that include featureid=
            for a in BeautifulSoup(body_html, "lxml").find_all("a", href=True):
                if "featureid=" in a["href"]:
                    part = a["href"].split("featureid=", 1)[-1]
                    cand = re.findall(r"\d+", part)
                    rm_ids.extend(cand)
            if not rm_ids:
                # last fallback: any 3-6 digit number in the body
                rm_ids = list(set(ID_RE.findall(body_html)))

        # Make rows
        for rid in sorted(set(rm_ids)):
            link = ROADMAP_LINK_FMT.format(id=rid)
            title = m.get("title") or ""
            # We do not have strong 'status/phase/targeted' from Graph MC messages, leave blank or try to scrape body later
            row = rows.get(rid) or {
                "id": rid,
                "title": title,
                "status": "",
                "phase": "",
                "targeted_dates": "",
                "cloud_instances": tenant_cloud or "",
                "link": link,
                "source": "Graph",
            }
            # Prefer earliest title if empty or update if this one is more descriptive
            if not row["title"] and title:
                row["title"] = title
            rows[rid] = row

    _debug_print(debug, f"[graph] extracted {len(rows)} roadmap rows")
    return list(rows.values())


# ---------------------------
# PUBLIC JSON
# ---------------------------

def fetch_public_json(debug: bool) -> List[Dict[str, Any]]:
    r = requests.get(PUBLIC_ROADMAP_JSON, timeout=60)
    r.raise_for_status()
    data = r.json()
    items = data if isinstance(data, list) else data.get("value") or data.get("items") or []
    _debug_print(debug, f"[public-json] got {len(items)} items")
    return items


def extract_roadmap_from_public_json(items: List[Dict[str, Any]],
                                     ids_filter: Optional[List[str]],
                                     tenant_cloud: Optional[str],
                                     debug: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for it in items:
        rid = str(it.get("id") or it.get("featureID") or "").strip()
        if not rid.isdigit():
            continue
        if ids_filter and rid not in ids_filter:
            continue

        title = it.get("title") or it.get("name") or ""
        status = it.get("status") or it.get("publicRoadmapStatus") or ""
        phase = (it.get("tagsContainer") or {}).get("releasePhase") or it.get("releasePhase") or ""
        targeted = it.get("publicDisclosureAvailabilityDate") or it.get("targetedDate") or ""
        # Cloud instances might live under tags or a flat list; normalize to CSV string
        clouds: List[str] = []
        tags = it.get("tags") or []
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, dict) and "tagName" in t:
                    clouds.append(t["tagName"])
        cloud_csv = ";".join(sorted(set(clouds)))

        # Tenant-cloud filter: if provided, check in cloud_csv or title/description
        if tenant_cloud:
            blob = " ".join([title or "", it.get("description") or "", cloud_csv or ""])
            if not cloud_matches(blob, tenant_cloud):
                continue

        rows.append({
            "id": rid,
            "title": title,
            "status": status if isinstance(status, str) else json.dumps(status),
            "phase": phase if isinstance(phase, str) else json.dumps(phase),
            "targeted_dates": targeted,
            "cloud_instances": cloud_csv,
            "link": ROADMAP_LINK_FMT.format(id=rid),
            "source": "PublicJSON",
        })
    _debug_print(debug, f"[public-json] extracted {len(rows)} rows (after filters)")
    return rows


# ---------------------------
# RSS
# ---------------------------

def fetch_public_rss(debug: bool) -> List[Dict[str, Any]]:
    feed = feedparser.parse(PUBLIC_ROADMAP_RSS)
    entries = feed.entries or []
    _debug_print(debug, f"[rss] got {len(entries)} entries")
    return entries


def extract_roadmap_from_rss(entries: List[Any],
                             ids_filter: Optional[List[str]],
                             tenant_cloud: Optional[str],
                             debug: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for e in entries:
        title = getattr(e, "title", "") or ""
        summary = getattr(e, "summary", "") or ""
        link = getattr(e, "link", "") or ""
        blob = " ".join([title, summary, link])

        # Pull ids from link or summary
        ids = []
        if "featureid=" in link:
            part = link.split("featureid=", 1)[-1]
            ids.extend(re.findall(r"\d+", part))
        if not ids:
            ids = ID_RE.findall(blob)

        for rid in sorted(set(ids)):
            if not rid.isdigit():
                continue
            if ids_filter and rid not in ids_filter:
                continue
            if tenant_cloud and not cloud_matches(blob, tenant_cloud):
                continue

            rows.append({
                "id": rid,
                "title": title,
                "status": "",
                "phase": "",
                "targeted_dates": "",
                "cloud_instances": tenant_cloud or "",
                "link": ROADMAP_LINK_FMT.format(id=rid),
                "source": "RSS",
            })
    _debug_print(debug, f"[rss] extracted {len(rows)} rows (after filters)")
    return rows


# ---------------------------
# MERGE & EMIT
# ---------------------------

def merge_rows(*groups: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for group in groups:
        for r in group or []:
            rid = r["id"]
            prev = by_id.get(rid)
            if not prev:
                by_id[rid] = r
            else:
                # Prefer Graph over PublicJSON over RSS for title/fields if missing
                priority = {"Graph": 3, "PublicJSON": 2, "RSS": 1}
                if priority.get(r.get("source", ""), 0) > priority.get(prev.get("source", ""), 0):
                    by_id[rid] = {**prev, **r}
                else:
                    # Fill blanks from the new row
                    for k in ("title", "status", "phase", "targeted_dates", "cloud_instances", "link"):
                        if not prev.get(k) and r.get(k):
                            prev[k] = r[k]
                    # keep prev source
    return sorted(by_id.values(), key=lambda x: int(x["id"]))


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    hdr = ["id", "title", "status", "phase", "targeted_dates", "cloud_instances", "link", "source"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        for r in rows:
            w.writerow([r.get(c, "") for c in hdr])


def write_json(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    debug = args.debug

    # Fast-path: explicit IDs provided
    if args.ids:
        ids = [x.strip() for x in args.ids.split(",") if x.strip().isdigit()]
        rows = [{
            "id": rid,
            "title": "",
            "status": "",
            "phase": "",
            "targeted_dates": "",
            "cloud_instances": args.tenant_cloud or "",
            "link": ROADMAP_LINK_FMT.format(id=rid),
            "source": "Explicit",
        } for rid in ids]
        if args.emit == "list":
            print(",".join([r["id"] for r in rows]))
        elif args.emit == "csv":
            if not args.out:
                raise SystemExit("--out is required for --emit csv")
            write_csv(args.out, rows)
        else:
            if not args.out:
                raise SystemExit("--out is required for --emit json")
            write_json(args.out, rows)

        # Stats
        if args.stats_out:
            with open(args.stats_out, "w", encoding="utf-8") as f:
                json.dump({"graph_rows": 0, "public_api_rows": 0, "rss_rows": 0, "explicit_ids": len(rows)}, f)
        return

    # Compute date window
    date_start, date_end = compute_range(args.months, args.since, args.until)
    _debug_print(debug, f"[filters] start={date_start} end={date_end} tenant_cloud={args.tenant_cloud}")

    # 1) Graph
    graph_rows: List[Dict[str, Any]] = []
    graph_err: Optional[str] = None
    if not args.no_graph and args.config:
        try:
            with open(args.config, "rb") as f:
                cfg = json.load(f)
            messages = fetch_graph_messages(cfg, debug=debug)
            graph_rows = extract_roadmap_from_graph(messages, date_start, date_end, args.tenant_cloud, debug=debug)
        except Exception as e:  # noqa: BLE001
            graph_err = str(e)
            _debug_print(debug, f"[graph] FAILED: {graph_err}")
    else:
        _debug_print(debug, "[graph] skipped (no config or --no-graph)")

    # 2) Public JSON
    public_rows: List[Dict[str, Any]] = []
    public_err: Optional[str] = None
    if not args.no_public_scrape:
        try:
            pub_items = fetch_public_json(debug=debug)
            # date filters are murky in public JSON; keep all, rely on tenant-cloud / later report filtering
            public_rows = extract_roadmap_from_public_json(pub_items, ids_filter=None, tenant_cloud=args.tenant_cloud, debug=debug)
        except Exception as e:  # noqa: BLE001
            public_err = str(e)
            _debug_print(debug, f"[public-json] FAILED: {public_err}")

    # 3) RSS
    rss_rows: List[Dict[str, Any]] = []
    rss_err: Optional[str] = None
    if not args.no_public_scrape:
        try:
            entries = fetch_public_rss(debug=debug)
            rss_rows = extract_roadmap_from_rss(entries, ids_filter=None, tenant_cloud=args.tenant_cloud, debug=debug)
        except Exception as e:  # noqa: BLE001
            rss_err = str(e)
            _debug_print(debug, f"[rss] FAILED: {rss_err}")

    # Merge (Graph wins over PublicJSON wins over RSS)
    merged = merge_rows(graph_rows, public_rows, rss_rows)

    # Apply final date filter to merged when we have a notion of date? (We only had dates from Graph)
    # Keep as-is; downstream post-process handles targeted dates from markdown.

    # Emit
    if args.emit == "list":
        print(",".join([r["id"] for r in merged]))
    elif args.emit == "csv":
        if not args.out:
            raise SystemExit("--out is required for --emit csv")
        write_csv(args.out, merged)
    else:
        if not args.out:
            raise SystemExit("--out is required for --emit json")
        write_json(args.out, merged)

    # Stats (and brief status text used by your workflow step)
    stats = {
        "graph_rows": len(graph_rows),
        "public_api_rows": len(public_rows),
        "rss_rows": len(rss_rows),
        "errors": {
            "graph": graph_err,
            "public_json": public_err,
            "rss": rss_err,
        },
    }
    if args.stats_out:
        os.makedirs(os.path.dirname(args.stats_out) or ".", exist_ok=True)
        with open(args.stats_out, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"[Fetch summary] Graph={len(graph_rows)} PublicJSON={len(public_rows)} RSS={len(rss_rows)}")
    if graph_err or public_err or rss_err:
        print("[Fetch warnings] One or more sources failed; see stats_out for details.", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
