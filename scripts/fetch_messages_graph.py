# -*- coding: utf-8 -*-
"""
fetch_messages_graph.py
Import-safe header so this script works whether called as:
  - python -m scripts.fetch_messages_graph ...
  - python scripts/fetch_messages_graph.py ...
"""

from __future__ import annotations

# stdlib imports you likely already have below; harmless if duplicated
import argparse
import csv
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

# --- import shim: allow both "python -m" and "python scripts/..." styles ---
REPO_ROOT = Path(__file__).resolve().parents[1]  # repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    # Preferred when run as a package: python -m scripts.fetch_messages_graph
    from scripts.report_templates import normalize_clouds, parse_date_soft
except ImportError:
    # Fallback when run as a file from the scripts/ directory
    from report_templates import normalize_clouds, parse_date_soft  # type: ignore[misc]

# Cloud helpers shared with generator/parser
# --- import shim: allow running as "python scripts/foo.py" or "-m scripts.foo"

ROOT = Path(__file__).resolve().parents[1]  # repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from scripts.report_templates import CLOUD_LABELS, normalize_clouds, parse_date_soft  # adjust names per file needs
except ImportError:
    # Fallback if running with sys.path[0] == scripts/
    from report_templates import CLOUD_LABELS, normalize_clouds, parse_date_soft  # noqa

# ------------------------------- CLI ---------------------------------
import argparse
from typing import Iterable, Set

def _as_set(x) -> Set[str]:
    """Normalize any value to a set of strings."""
    if x is None:
        return set()
    if isinstance(x, (set, list, tuple)):
        return {str(v) for v in x}
    return {str(x)}

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="fetch_messages_graph",
        description="Fetch M365 roadmap/messages from Graph and RSS and emit CSV/JSON."
    )

    # Inputs / filters
    p.add_argument("--config", dest="config", default=None,
                   help="Path to graph_config.json (contains pfx_base64, tenant, client).")
    p.add_argument("--since", dest="since", default=None,
                   help="Only include items modified on/after this date (YYYY-MM-DD).")
    p.add_argument("--months", dest="months", type=int, default=None,
                   help="Relative time window in months from today.")
    p.add_argument("--cloud", dest="clouds", action="append", default=[],
                   help="Cloud filter; repeatable. e.g. --cloud 'Worldwide (Standard Multi-Tenant)'")

    # Behavior flags
    p.add_argument("--no-window", dest="no_window", action="store_true",
                   help="Headless auth only (no device/browser window).")

    # Outputs
    p.add_argument("--emit", choices=["csv", "json"], required=True,
                   help="Output format to emit.")
    p.add_argument("--out", required=True,
                   help="Output file path for --emit.")
    p.add_argument("--stats-out", dest="stats_out", default=None,
                   help="Optional: write fetch statistics JSON here.")

    # Optional explicit include list
    p.add_argument("--public-ids", dest="public_ids", default=None,
                   help="Comma-separated explicit Roadmap IDs to include.")

    args = p.parse_args(argv)

    # Normalize clouds into a set of canonical labels
    selected: Set[str] = set()
    for c in args.clouds:
        normalized = normalize_clouds(c)   # your existing helper; may return "General" or ["General", ...]
        selected |= _as_set(normalized)
    args.clouds = selected  # downstream code can use a set[str]

    # Normalize public_ids into a set if provided
    if args.public_ids:
        args.public_ids = {pid.strip() for pid in args.public_ids.split(",") if pid.strip()}

    return args

# ----------------------------- Utilities ------------------------------

HEADERS_MASTER = [
    "PublicId",
    "Title",
    "Source",
    "Product_Workload",
    "Status",
    "LastModified",
    "ReleaseDate",
    "Cloud_instance",
    "Official_Roadmap_link",
    "MessageId",
]

ROADMAP_LINK_TMPL = "https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={id}"

# Very tolerant Roadmap-ID scraping from HTML bodies (Graph) or RSS descriptions
_RE_ROADMAP_ID = re.compile(
    r"(?:Roadmap\s*ID|Feature\s*ID|Roadmap\s*#|Feature\s*#)\D{0,10}(\d{3,8})",
    re.I,
)

_RE_ANY_ID = re.compile(r"\b(\d{4,8})\b")

_RE_CLOUD = re.compile(r"Cloud\s*Instance:\s*([^<\n\r]+)", re.I)
_RE_STATUS = re.compile(r"Status:\s*([^<\n\r]+)", re.I)
_RE_WORKLOAD = re.compile(r"(?:Workload|Product):\s*([^<\n\r]+)", re.I)
_RE_RELEASE = re.compile(r"(?:Release\s*(?:date|phase)?\s*:\s*|GA\s*:\s*)([^<\n\r]+)", re.I)


def safe_get(d: Dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def to_iso(dt_str: str) -> str:
    """Best-effort to normalize dates to ISO."""
    d = parse_date_soft(dt_str)
    return d.strftime("%Y-%m-%d") if d else (dt_str.strip() if dt_str else "")


# ------------------------- Public helpers (tests) ---------------------

def extract_roadmap_ids_from_html(html_text: str) -> List[str]:
    """
    Extract plausible roadmap IDs from an HTML (or text) blob.
    Prefers labeled forms like 'Roadmap ID: 123456' but will fall back
    to bare 4-8 digit numbers when present.
    """
    if not html_text:
        return []
    text = html.unescape(html_text)
    ids = set(m.group(1) for m in _RE_ROADMAP_ID.finditer(text))
    if not ids:
        ids = set(m.group(1) for m in _RE_ANY_ID.finditer(text))
    # Drop obvious non-roadmap values (leading zeros or too big/small)
    out = [i.lstrip("0") or "0" for i in ids if 1000 <= int(i) <= 99999999]
    return sorted(set(out), key=int)


def include_by_cloud(row_cloud_field: str, selected: Set[str]) -> bool:
    """
    Determine if a row with 'Cloud_instance' should be included for selected clouds.
    Missing cloud is treated as 'General' only if 'General' was requested.
    """
    if not selected:
        return True
    tags = normalize_clouds(row_cloud_field)
    if tags:
        return bool(tags & selected)
    return "General" in selected


# ------------------------------ Fetchers ------------------------------

def fetch_graph_rows(cfg_path: Optional[str], since_dt: Optional[dt.datetime], sources: Dict[str, int], errors: List[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if GraphClient is None or GraphConfig is None:
        return rows

    # Build config
    try:
        if cfg_path:
            cfg = GraphConfig.from_file(cfg_path)
        else:
            cfg = GraphConfig.from_env()
    except Exception as e:
        errors.append(f"graph-config: {e}")
        return rows

    try:
        cli = GraphClient(cfg)
        it = cli.iter_service_messages(
            top=100,
            last_modified_ge=None if not since_dt else since_dt,
        )
        for msg in it:
            sources["graph-raw"] = sources.get("graph-raw", 0) + 1
            title = (msg.get("title") or "").strip()
            mid = (msg.get("id") or "").strip()
            lm = (msg.get("lastModifiedDateTime") or "").strip()
            last_mod = to_iso(lm)

            # Services/workloads is a list
            services = msg.get("services") or []
            product = ", ".join([s for s in services if isinstance(s, str)]) if isinstance(services, list) else ""

            # Body content
            body_html = safe_get(msg, "body", "content", default="") or ""
            rids = extract_roadmap_ids_from_html(body_html)

            if not rids:
                # Still record a message row without a Roadmap ID (optional)
                continue

            for rid in rids:
                row = {
                    "PublicId": rid,
                    "Title": title,
                    "Source": "graph",
                    "Product_Workload": product,
                    "Status": "",  # Graph messages don't map cleanly to Roadmap status
                    "LastModified": last_mod,
                    "ReleaseDate": "",
                    "Cloud_instance": "",  # not directly in Graph message; downstream may enrich
                    "Official_Roadmap_link": ROADMAP_LINK_TMPL.format(id=rid),
                    "MessageId": mid,
                }
                rows.append(row)
                sources["graph"] = sources.get("graph", 0) + 1

    except Exception as e:
        errors.append(f"graph-fetch: {e}")

    return rows


def fetch_rss_rows(since_dt: Optional[dt.datetime], sources: Dict[str, int], errors: List[str]) -> List[Dict[str, str]]:
    """
    Minimal dependency RSS fetch for the public Roadmap feed.
    """
    rows: List[Dict[str, str]] = []
    url = "https://www.microsoft.com/en-us/microsoft-365/RoadmapFeatureRSS"
    try:
        resp = requests.get(url, timeout=(10, 30))
        resp.raise_for_status()
        xml = resp.text
    except Exception as e:
        errors.append(f"rss-fetch: {e}")
        return rows

    # Crude item splitting; the feed is simple enough for this.
    items = re.split(r"</item>\s*<item>", xml, flags=re.I)
    if items:
        # normalize: first/last may have surrounding tags
        if items[0].strip().endswith("</item>"):
            pass
        else:
            # remove header up to first <item>
            first_split = re.split(r"<item>", items[0], flags=re.I)
            items[0] = first_split[-1]
        if items[-1].strip().startswith("<item>"):
            pass
        else:
            # strip closing tags after last </item>
            items[-1] = re.split(r"</item>", items[-1], 1, flags=re.I)[0]

    for raw in items:
        if "<title>" not in raw:
            continue
        sources["rss-raw"] = sources.get("rss-raw", 0) + 1

        title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", raw, re.I | re.S)
        ttext = html.unescape((title.group(1) or title.group(2) or "").strip()) if title else ""

        linkm = re.search(r"<link>(.*?)</link>", raw, re.I | re.S)
        link = (linkm.group(1).strip() if linkm else "")

        descm = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>", raw, re.I | re.S)
        desc = (descm.group(1) or descm.group(2) or "").strip() if descm else ""

        pubm = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.I | re.S)
        pub = (pubm.group(1).strip() if pubm else "")
        # Some feeds include lastUpdate - we stick to pubDate if present

        # Extract metadata from description HTML/text
        rid_list = extract_roadmap_ids_from_html(desc) or extract_roadmap_ids_from_html(ttext) or extract_roadmap_ids_from_html(link)
        cloud_val = (re.search(_RE_CLOUD, desc or "") or re.search(_RE_CLOUD, ttext or "") or re.search(_RE_CLOUD, link or ""))
        status_val = (re.search(_RE_STATUS, desc or "") or re.search(_RE_STATUS, ttext or ""))
        workload_val = (re.search(_RE_WORKLOAD, desc or "") or re.search(_RE_WORKLOAD, ttext or ""))
        release_val = (re.search(_RE_RELEASE, desc or "") or None)

        clouds = cloud_val.group(1).strip() if cloud_val else ""
        status = status_val.group(1).strip() if status_val else ""
        workload = workload_val.group(1).strip() if workload_val else ""
        release = to_iso(release_val.group(1)) if release_val else ""

        # If no explicit roadmap ID extracted, try the link querystring (?filters=&searchterms=123456)
        if not rid_list and "searchterms=" in link:
            try:
                rid_list = [re.search(r"searchterms=(\d+)", link).group(1)]
            except Exception:
                pass

        if not rid_list:
            continue

        for rid in rid_list:
            row = {
                "PublicId": rid,
                "Title": ttext,
                "Source": "rss",
                "Product_Workload": workload,
                "Status": status,
                "LastModified": to_iso(pub),
                "ReleaseDate": release,
                "Cloud_instance": clouds,
                "Official_Roadmap_link": link or ROADMAP_LINK_TMPL.format(id=rid),
                "MessageId": "",  # not applicable for RSS
            }
            rows.append(row)
            sources["rss"] = sources.get("rss", 0) + 1

    return rows


# --------------------------- Transformations --------------------------

def apply_window(rows: List[Dict[str, str]], since_dt: Optional[dt.datetime]) -> List[Dict[str, str]]:
    if since_dt is None:
        return rows
    out: List[Dict[str, str]] = []
    for r in rows:
        d = parse_date_soft(r.get("LastModified") or r.get("ReleaseDate") or "")
        if d and d >= since_dt:
            out.append(r)
    return out


def dedupe_latest(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Keep the latest record per PublicId, based on LastModified/ReleaseDate.
    """
    best: Dict[str, Tuple[dt.datetime, Dict[str, str]]] = {}
    for r in rows:
        pid = (r.get("PublicId") or "").strip()
        if not pid:
            continue
        d = parse_date_soft(r.get("LastModified") or r.get("ReleaseDate") or "") or dt.datetime.min
        cur = best.get(pid)
        if cur is None or d >= cur[0]:
            best[pid] = (d, r)
    return [v[1] for v in best.values()]


def filter_by_cloud(rows: List[Dict[str, str]], selected: Set[str]) -> List[Dict[str, str]]:
    if not selected:
        return rows
    return [r for r in rows if include_by_cloud(r.get("Cloud_instance", ""), selected)]


def sort_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def key(r: Dict[str, str]):
        d = parse_date_soft(r.get("LastModified") or r.get("ReleaseDate") or "") or dt.datetime.min
        return (d, r.get("PublicId") or "")
    return sorted(rows, key=key, reverse=True)


# ------------------------------ Writers -------------------------------

def write_csv(out_path: Path, rows: List[Dict[str, str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS_MASTER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in HEADERS_MASTER})


def write_json(out_path: Path, rows: List[Dict[str, str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------- Main --------------------------------

def months_to_dt_utc_approx(months: int) -> dt.datetime:
    days = max(1, int(months) * 30)
    return dt.datetime.utcnow() - dt.timedelta(days=days)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    sources: Dict[str, int] = {}
    errors: List[str] = []

    # Date window
    since_dt: Optional[dt.datetime] = None
    if not args.no_window:
        if args.months is not None:
            since_dt = months_to_dt_utc_approx(args.months)
        if args.since:
            try:
                since_dt = dt.datetime.strptime(args.since.strip(), "%Y-%m-%d")
            except Exception:
                pass

    # Fetch
    all_rows: List[Dict[str, str]] = []

    if not args.no_graph:
        all_rows += fetch_graph_rows(args.config, since_dt, sources, errors)

    if not args.no_public_scrape:
        all_rows += fetch_rss_rows(since_dt, sources, errors)

    # Forced IDs (always include as skeletal rows)
    forced_ids = [x.strip() for x in (args.ids or "").replace(";", ",").split(",") if x.strip()]
    for fid in forced_ids:
        row = {
            "PublicId": fid,
            "Title": "",
            "Source": "forced",
            "Product_Workload": "",
            "Status": "",
            "LastModified": "",
            "ReleaseDate": "",
            "Cloud_instance": "",
            "Official_Roadmap_link": ROADMAP_LINK_TMPL.format(id=fid),
            "MessageId": "",
        }
        all_rows.append(row)
        sources["forced"] = sources.get("forced", 0) + 1

    # Transform
    pre_count = len(all_rows)
    all_rows = dedupe_latest(all_rows)
    all_rows = filter_by_cloud(all_rows, args.selected_clouds)
    all_rows = sort_rows(all_rows)

    # Emit
    out_path = Path(args.out)
    if args.emit == "csv":
        write_csv(out_path, all_rows)
    else:
        write_json(out_path, all_rows)

    # Stats
    if args.stats_out:
        stats_path = Path(args.stats_out)
        stats = {
            "rows": len(all_rows),
            "sources": sources,
            "errors": errors,
            "selected_clouds": sorted(args.selected_clouds),
            "window_since": since_dt.isoformat() if since_dt else "",
            "pre_dedupe": pre_count,
        }
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        for e in errors:
            print(f"WARN: {e}", file=sys.stderr)

    print(f"Done. rows={len(all_rows)} sources={sources} errors={len(errors)}")


if __name__ == "__main__":
    main()
