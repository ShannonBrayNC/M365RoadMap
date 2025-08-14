#!/usr/bin/env python3
"""
parse_roadmap_markdown.py

Parses a Microsoft 365 Roadmap Markdown report into CSV/JSON.
Optionally falls back to the official RSS/JSON API if requested.

Master schema (output columns):
  ["ID","Title","Product/Workload","Status","Release phase",
   "Targeted dates","Cloud instance","Short description","Official Roadmap link"]

Features
--------
- Robust pipe-table parsing (first table with a '|---' separator)
- Header normalization to the master schema (extra columns ignored)
- Filters:
    --months (1..24), --since YYYY-MM-DD, --until YYYY-MM-DD
    --include (Cloud instance contains), --exclude (Cloud instance contains)
    --ids (comma-separated whitelist of IDs)
- One-line summary + optional --fail-on-empty
- Fallback to Microsoft’s supported JSON API (behind the public RSS):
    https://www.microsoft.com/releasecommunications/api/v2/m365/rss
  via flags: --fallback-rss [--merge-fallback] [--rss-url URL]

Examples
--------
# Convert MD -> CSV/JSON (warn if empty, do not fail)
python scripts/parse_roadmap_markdown.py output/roadmap_report.md \
  --csv output/roadmap_report.csv --json output/roadmap_report.json

# Fail CI when filters remove all rows
python scripts/parse_roadmap_markdown.py output/roadmap_report.md \
  --csv output/roadmap_report.csv --fail-on-empty

# Try RSS/JSON fallback if markdown has no rows (and merge results)
python scripts/parse_roadmap_markdown.py output/roadmap_report.md \
  --csv output/roadmap_report.csv --fallback-rss --merge-fallback

"""

from __future__ import annotations
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Iterable, Any, Optional

import requests

MASTER_HEADERS = [
    "ID",
    "Title",
    "Product/Workload",
    "Status",
    "Release phase",
    "Targeted dates",
    "Cloud instance",
    "Short description",
    "Official Roadmap link",
]

# ---------------------------
# Utilities
# ---------------------------

def _norm(s: Any) -> str:
    """Normalize text: remove zero-width, collapse spaces, replace '|' to avoid table conflicts."""
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\u200b", "").replace("|", " / ")
    return " ".join(s.split())

def _try_parse_month_year(s: str) -> Optional[datetime]:
    """Parse strings like 'September CY2025' or 'August 2025' to first-of-month datetime."""
    if not s:
        return None
    s2 = s.strip()
    s2 = s2.replace("CY", "").replace("cy", "").replace(",", " ")
    s2 = re.sub(r"\s+", " ", s2).strip()
    # Accept forms like 'September 2025'
    try:
        return datetime.strptime(s2, "%B %Y").replace(day=1)
    except Exception:
        pass
    # Try 'Sep 2025'
    try:
        return datetime.strptime(s2, "%b %Y").replace(day=1)
    except Exception:
        pass
    # Try YYYY-MM-DD
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(s2, fmt)
            return dt.replace(day=1)
        except Exception:
            pass
    # Extract month + year tokens loosely
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(\d{4})", s2, re.I)
    if m:
        mm = m.group(1)[:3].title()
        yy = m.group(2)
        try:
            return datetime.strptime(f"{mm} {yy}", "%b %Y").replace(day=1)
        except Exception:
            pass
    y = re.search(r"\b(20\d{2})\b", s2)
    if y:
        # If only a year is provided, treat as January of that year
        try:
            return datetime(int(y.group(1)), 1, 1)
        except Exception:
            pass
    return None

def _in_months_window(dt: Optional[datetime], months: Optional[int]) -> bool:
    if not months or not dt:
        return True
    # months back from "now" (UTC-agnostic; month resolution)
    now = datetime.utcnow()
    # compute cutoff = first day of month N months ago
    y, m = now.year, now.month
    m -= months
    while m <= 0:
        m += 12
        y -= 1
    cutoff = datetime(y, m, 1)
    return dt >= cutoff

def _in_since_until(dt: Optional[datetime], since: Optional[str], until: Optional[str]) -> bool:
    if not dt:
        return True
    if since:
        try:
            sdt = datetime.strptime(since, "%Y-%m-%d")
            if dt < sdt:
                return False
        except Exception:
            pass
    if until:
        try:
            udt = datetime.strptime(until, "%Y-%m-%d")
            if dt > udt:
                return False
        except Exception:
            pass
    return True

def _contains_ci(row_ci: str, needle: str) -> bool:
    return needle.lower() in (row_ci or "").lower()

def _split_ids(ids: str) -> List[str]:
    return [i.strip() for i in (ids or "").split(",") if i.strip()]

# ---------------------------
# Markdown table parsing
# ---------------------------

HEADER_ALIASES = {
    "id": "ID",
    "feature id": "ID",
    "featureid": "ID",
    "title": "Title",
    "product": "Product/Workload",
    "product/workload": "Product/Workload",
    "workload": "Product/Workload",
    "status": "Status",
    "release phase": "Release phase",
    "targeted dates": "Targeted dates",
    "targeted": "Targeted dates",
    "ga": "Targeted dates",
    "general availability": "Targeted dates",
    "cloud instance": "Cloud instance",
    "cloud instances": "Cloud instance",
    "short description": "Short description",
    "official roadmap link": "Official Roadmap link",
    "roadmap link": "Official Roadmap link",
    "link": "Official Roadmap link",
}

DATE_HEADER_CANDIDATES = [
    "Targeted dates",
    "Targeted Release",
    "Release",
    "GA",
    "General Availability",
]

def _normalize_header(h: str) -> str:
    k = _norm(h).lower()
    return HEADER_ALIASES.get(k, _norm(h))

def _find_first_table_lines(md_text: str) -> Tuple[List[str], int, int]:
    """
    Return table lines (including header + separator + rows) and (start,end) line indexes.
    Looks for first header separator like: | --- | --- |
    """
    lines = md_text.splitlines()
    sep_index = -1
    for i, ln in enumerate(lines):
        if re.match(r"^\s*\|?\s*:?-{3,}\s*(\|\s*:?-{3,}\s*)+\|?\s*$", ln):
            sep_index = i
            break
    if sep_index == -1:
        return [], -1, -1
    # walk back to find header line
    header_index = sep_index - 1
    while header_index >= 0 and lines[header_index].strip() == "":
        header_index -= 1
    if header_index < 0:
        return [], -1, -1
    # collect rows forward until a non-table line (no leading '|' and not matching cell pattern)
    start = header_index
    end = sep_index + 1
    while end < len(lines):
        ln = lines[end]
        if not ln.strip():
            break
        if "|" not in ln:
            break
        end += 1
    return lines[start:end], start, end

def _split_row(line: str) -> List[str]:
    # split respecting pipes; strip outer pipes
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    parts = [p.strip() for p in s.split("|")]
    return parts

def parse_markdown_table(md_path: str) -> Tuple[List[str], List[List[str]]]:
    """
    Returns (headers, rows). Headers are normalized to master schema names where possible.
    """
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    table_lines, s, e = _find_first_table_lines(text)
    if not table_lines:
        return [], []

    header_cells = _split_row(table_lines[0])
    # Normalize headers
    norm_headers = [_normalize_header(h) for h in header_cells]

    # data rows (skip header + separator)
    rows: List[List[str]] = []
    for ln in table_lines[2:]:
        if not ln.strip() or re.match(r"^\s*<!--", ln):
            continue
        if "|" not in ln:
            continue
        cells = _split_row(ln)
        # pad/truncate to header length
        if len(cells) < len(norm_headers):
            cells += [""] * (len(norm_headers) - len(cells))
        elif len(cells) > len(norm_headers):
            cells = cells[:len(norm_headers)]
        rows.append([_norm(c) for c in cells])

    return norm_headers, rows

def rows_to_master(headers: List[str], rows: List[List[str]]) -> List[Dict[str, str]]:
    """
    Map arbitrary header set to MASTER_HEADERS (missing columns -> "")
    """
    index = {h: i for i, h in enumerate(headers)}
    out: List[Dict[str, str]] = []
    for r in rows:
        def cell(name: str) -> str:
            if name in index:
                return r[index[name]]
            return ""
        out.append({
            "ID": cell("ID"),
            "Title": cell("Title"),
            "Product/Workload": cell("Product/Workload"),
            "Status": cell("Status"),
            "Release phase": cell("Release phase"),
            "Targeted dates": cell("Targeted dates"),
            "Cloud instance": cell("Cloud instance"),
            "Short description": cell("Short description"),
            "Official Roadmap link": cell("Official Roadmap link"),
        })
    return out

# ---------------------------
# Filtering
# ---------------------------

def _extract_date_from_row(row: Dict[str, str]) -> Optional[datetime]:
    # try multiple headers
    for name in DATE_HEADER_CANDIDATES:
        v = row.get(name) or row.get("Targeted dates")
        if v:
            dt = _try_parse_month_year(v)
            if dt:
                return dt
    return _try_parse_month_year(row.get("Targeted dates",""))

def filter_rows(
    rows: List[Dict[str, str]],
    months: Optional[int],
    since: Optional[str],
    until: Optional[str],
    include_ci: Optional[str],
    exclude_ci: Optional[str],
    ids_whitelist: Optional[List[str]],
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    ids_set = set(ids_whitelist or [])
    for r in rows:
        # ID whitelist (if provided)
        if ids_set and r.get("ID") and r["ID"] not in ids_set:
            continue
        # Cloud instance include/exclude
        ci = r.get("Cloud instance", "")
        if include_ci and not _contains_ci(ci, include_ci):
            continue
        if exclude_ci and _contains_ci(ci, exclude_ci):
            continue
        # Date filters
        dt = _extract_date_from_row(r)
        if months and not _in_months_window(dt, months):
            continue
        if not _in_since_until(dt, since, until):
            continue
        out.append(r)
    return out

# ---------------------------
# RSS/JSON fallback
# ---------------------------

DEFAULT_RSS_URL = "https://www.microsoft.com/releasecommunications/api/v2/m365/rss"

def _pluck(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def _string_list(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return ", ".join(_norm(v) for v in val if v)
    return _norm(val)

def _rss_first(*vals: Any) -> str:
    for v in vals:
        nv = _norm(v)
        if nv:
            return nv
    return ""

def _rss_feature_id(item: Dict[str, Any]) -> str:
    return _rss_first(_pluck(item, "featureId", "FeatureId", "id", "ID", "Id"))

def _rss_title(item: Dict[str, Any]) -> str:
    return _rss_first(_pluck(item, "title", "Title", "featureTitle", "FeatureTitle"),
                      _pluck(item, "summary", "Summary"))

def _rss_product(item: Dict[str, Any]) -> str:
    return _rss_first(_string_list(_pluck(item, "products", "Products", "workload", "Workload", "workloads", "Workloads")),
                      _string_list(_pluck(item, "tags", "Tags")))

def _rss_status(item: Dict[str, Any]) -> str:
    return _rss_first(_pluck(item, "status", "Status", "publicRoadmapStatus", "PublicRoadmapStatus"))

def _rss_phase(item: Dict[str, Any]) -> str:
    return _rss_first(_pluck(item, "releasePhase", "ReleasePhase"))

def _rss_target(item: Dict[str, Any]) -> str:
    return _rss_first(_pluck(item, "targeted", "Targeted"),
                      _pluck(item, "ga", "GA", "generalAvailability", "GeneralAvailability"),
                      _pluck(item, "publicPreviewDate", "PublicPreviewDate"),
                      _pluck(item, "releaseDate", "ReleaseDate"))

def _rss_cloud(item: Dict[str, Any]) -> str:
    return _string_list(_pluck(item, "cloudInstances", "CloudInstances", "cloudInstance", "CloudInstance"))

def _rss_desc(item: Dict[str, Any]) -> str:
    return _rss_first(_pluck(item, "description", "Description", "shortDescription", "ShortDescription",
                             "summary", "Summary"))

def _rss_link(item: Dict[str, Any], fid: str) -> str:
    L = _rss_first(_pluck(item, "link", "Link", "moreInfoLink", "MoreInfoLink"),
                   _pluck(item, "url", "Url", "URL"))
    return L or (f"https://www.microsoft.com/en-us/microsoft-365/roadmap?id={fid}" if fid else "")

def _rss_to_row(item: Dict[str, Any]) -> Dict[str, str]:
    fid = _rss_feature_id(item)
    return {
        "ID": fid,
        "Title": _rss_title(item),
        "Product/Workload": _rss_product(item),
        "Status": _rss_status(item),
        "Release phase": _rss_phase(item),
        "Targeted dates": _rss_target(item),
        "Cloud instance": _rss_cloud(item),
        "Short description": _rss_desc(item),
        "Official Roadmap link": _rss_link(item, fid),
    }

def _rss_fetch_all(rss_url: str) -> List[Dict[str, Any]]:
    r = requests.get(rss_url, timeout=60)
    r.raise_for_status()
    data = r.json()
    # find a list payload
    for key in ("value", "items", "Items", "results", "Results", "data", "Data"):
        if isinstance(data.get(key), list):
            return data[key]
    if isinstance(data, list):
        return data
    return []

def fallback_from_rss(ids: List[str], rss_url: str) -> List[Dict[str, str]]:
    if not ids:
        return []
    raw = _rss_fetch_all(rss_url)
    wanted = set(ids)
    out: List[Dict[str, str]] = []
    for it in raw:
        fid = _rss_feature_id(it)
        if fid and fid in wanted:
            out.append(_rss_to_row(it))
    return out

# ---------------------------
# I/O
# ---------------------------

def write_csv(rows: List[Dict[str, str]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MASTER_HEADERS)
        w.writeheader()
        for r in rows:
            w.writerow({k: _norm(r.get(k, "")) for k in MASTER_HEADERS})

def write_json(rows: List[Dict[str, str]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{k: _norm(r.get(k, "")) for k in MASTER_HEADERS} for r in rows],
                  f, ensure_ascii=False, indent=2)

# ---------------------------
# Main
# ---------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Parse M365 Roadmap Markdown to CSV/JSON (with optional RSS/JSON fallback)")
    ap.add_argument("input", help="Input Markdown file path")
    ap.add_argument("--csv", help="Output CSV path")
    ap.add_argument("--json", help="Output JSON path")
    ap.add_argument("--months", type=int, default=None, help="Filter to last N months (1..24)")
    ap.add_argument("--since", default=None, help="Filter since date YYYY-MM-DD")
    ap.add_argument("--until", default=None, help="Filter until date YYYY-MM-DD")
    ap.add_argument("--include", default=None, help="Only include rows where Cloud instance contains this text")
    ap.add_argument("--exclude", default=None, help="Exclude rows where Cloud instance contains this text")
    ap.add_argument("--ids", default=None, help="Comma-separated Roadmap IDs to keep (whitelist)")
    ap.add_argument("--fail-on-empty", action="store_true", help="Exit with code 2 if no rows remain after filtering")
    # Fallback RSS
    ap.add_argument("--fallback-rss", action="store_true", help="If the Markdown has 0 rows, fetch IDs via RSS/JSON API")
    ap.add_argument("--merge-fallback", action="store_true", help="Merge RSS rows with MD rows (otherwise replace when fallback is used)")
    ap.add_argument("--rss-url", default=DEFAULT_RSS_URL, help="Override RSS/JSON API URL")
    args = ap.parse_args()

    # 1) Parse markdown table
    headers, matrix = parse_markdown_table(args.input)
    md_rows = rows_to_master(headers, matrix) if headers and matrix else []

    # 2) Apply filters to MD rows
    ids_whitelist = _split_ids(args.ids or "")
    md_rows_f = filter_rows(
        md_rows,
        months=args.months,
        since=args.since,
        until=args.until,
        include_ci=args.include,
        exclude_ci=args.exclude,
        ids_whitelist=ids_whitelist,
    )

    # 3) Optionally use RSS fallback if nothing in MD (or if user wants to always merge)
    used_fallback = False
    fb_rows_f: List[Dict[str, str]] = []
    if args.fallback_rss and (len(md_rows_f) == 0):
        used_fallback = True
        # If ids were provided, limit RSS fetch to those; else, try to infer IDs from MD (none if MD empty)
        rss_ids = ids_whitelist
        fb_rows = fallback_from_rss(rss_ids, args.rss_url) if rss_ids else []
        # Apply same filters to fallback rows (date/ci filters)
        fb_rows_f = filter_rows(
            fb_rows,
            months=args.months,
            since=args.since,
            until=args.until,
            include_ci=args.include,
            exclude_ci=args.exclude,
            ids_whitelist=ids_whitelist,
        )
        # Replace (default) or merge
        if args.merge_fallback:
            md_rows_f = fb_rows_f
        else:
            md_rows_f = fb_rows_f  # replacing since MD set is empty anyway

    # 4) Summary + fail-on-empty
    parsed_count = len(md_rows)
    kept_count = len(md_rows_f)
    print(f"[summary] parsed={parsed_count} kept={kept_count} months={args.months or ''} since={args.since or ''} until={args.until or ''} include={args.include or ''} exclude={args.exclude or ''} ids={','.join(ids_whitelist) if ids_whitelist else ''} fallback={'RSS' if used_fallback else 'none'}")
    if kept_count == 0:
        print("[warning] No matches found after filtering.", file=sys.stderr)
        if args.fail_on_empty:
            sys.exit(2)

    # 5) Write outputs
    if args.csv:
        write_csv(md_rows_f, args.csv)
    if args.json:
        write_json(md_rows_f, args.json)

if __name__ == "__main__":
    main()
