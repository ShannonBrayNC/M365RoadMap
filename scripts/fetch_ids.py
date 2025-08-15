#!/usr/bin/env python3
"""
fetch_ids.py v1.6 — Microsoft 365 Roadmap ID discovery via official JSON API

Features
- Uses public JSON endpoint (no scraping)
- UTF-8 safe on Windows (stdout + file)
- Filters by date window (strict or loose) and cloud instances
- Robust parsing:
  * ISO-like dates (YYYY-MM-DD, etc.)
  * M365 fuzzy dates: "August CY2025", "Q3 CY2025", "H1 2025", "2025"
  * tagsContainer fields may be strings or dicts; normalize both
- CLI:
  --months STR|INT         1..6 ("" means no months filter)
  --since YYYY-MM-DD
  --until YYYY-MM-DD
  --keep-undated true|false  (default false)  # when a date filter is set
  --include TEXT           comma-separated instances (e.g., "GCC,GCC High,DoD")
  --exclude TEXT
  --emit list|csv          default: list (prints "id1,id2,...")
  --out PATH               when --emit csv, write UTF-8 CSV here
  --max-items INT          cap items (0 = no cap)
  --max-pages INT          accepted for backward-compat, ignored
  --debug                  print diagnostics to stderr
"""

import argparse
import csv
import re
import sys
from datetime import datetime, timedelta

import requests

API = "https://www.microsoft.com/releasecommunications/api/v1/m365"

# ---------- stdout: force UTF-8 on Windows consoles ----------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------- helpers ----------


def clean_text(s):
    """Remove zero-width spaces and normalize whitespace; keep real Unicode."""
    if not isinstance(s, str):
        return s
    s = s.replace("\u200b", "")  # zero-width space
    return " ".join(s.split())


def coerce_months(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    try:
        n = int(s)
        return n if 1 <= n <= 6 else None
    except Exception:
        return None


def norm_instance(s: str) -> str:
    if not s:
        return ""
    t = s.strip().lower()
    if t in ("worldwide", "standard multi-tenant", "worldwide (standard multi-tenant)"):
        return "worldwide (standard multi-tenant)"
    if t in ("gcc high", "gcch"):
        return "gcc high"
    if t in ("us dod", "dod"):
        return "dod"
    if t in ("us gcc", "gcc"):
        return "gcc"
    return t  # leave other values as-is (lowercased)


def parse_isoish(dt_str: str | None):
    if not dt_str:
        return None
    fmts = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ")
    for fmt in fmts:
        try:
            return datetime.strptime(dt_str[: len(fmt)], fmt)
        except Exception:
            pass
    return None


def parse_m365_fuzzy(dt_str: str | None):
    """Parse 'August CY2025', 'Q3 CY2025', 'H1 2025', '2025'."""
    if not dt_str:
        return None
    s = dt_str.strip()
    # Remove "CY"
    s = re.sub(r"\bCY\s*", "", s, flags=re.IGNORECASE)

    # Month Year
    try:
        return datetime.strptime(s, "%B %Y")
    except Exception:
        pass

    # Quarter
    m = re.match(r"^Q([1-4])\s+(\d{4})$", s, re.IGNORECASE)
    if m:
        q = int(m.group(1))
        y = int(m.group(2))
        start_month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
        return datetime(y, start_month, 1)

    # Half
    m = re.match(r"^H([12])\s+(\d{4})$", s, re.IGNORECASE)
    if m:
        h = int(m.group(1))
        y = int(m.group(2))
        start_month = {1: 1, 2: 7}[h]
        return datetime(y, start_month, 1)

    # Year only
    m = re.match(r"^(\d{4})$", s)
    if m:
        return datetime(int(m.group(1)), 1, 1)

    return None


def parse_any_date(dt_str: str | None):
    d = parse_isoish(dt_str)
    if d:
        return d
    return parse_m365_fuzzy(dt_str)


def instances_for(item):
    """
    Return a normalized list of cloud instances.
    Handles both strings and dicts like {"tagName": "GCC High"}.
    Also checks flat tags for instance-ish values.
    """
    tc = item.get("tagsContainer") or item.get("TagsContainer") or {}
    vals = tc.get("cloudInstances") or tc.get("CloudInstances") or []

    norm_vals = []
    for v in vals:
        if isinstance(v, dict):
            v = v.get("tagName") or v.get("name") or v.get("value") or ""
        if isinstance(v, str) and v.strip():
            norm_vals.append(norm_instance(v))

    # Fallback to flat tags
    if not norm_vals:
        tags = item.get("tags") or item.get("Tags") or []
        for t in tags:
            if isinstance(t, dict):
                t = t.get("tagName") or t.get("name") or t.get("value") or ""
            if isinstance(t, str) and any(k in t.lower() for k in ("gcc", "dod", "worldwide")):
                norm_vals.append(norm_instance(t))

    return [v for v in norm_vals if v]


def instance_allowed(item, include_set, exclude_set):
    vals = instances_for(item)
    if exclude_set and any(v in exclude_set for v in vals):
        return False
    if include_set:
        if not vals:  # keep unknowns when include_set is present? choose conservative:
            # Conservative approach: do NOT keep unknowns when include filter is set.
            return False
        return any(v in include_set for v in vals)
    return True


def in_date_window(item, months, since_dt, until_dt, keep_undated=False):
    """
    Date filter using several fields. If any filter is set and no date is parseable,
    keep only if keep_undated=True (default False = strict).
    """
    if not (months or since_dt or until_dt):
        return True

    candidates = [
        item.get("releaseDate"),
        item.get("publicPreviewDate"),
        item.get("rolloutStart"),
        item.get("publicDisclosureAvailabilityDate"),
        item.get("modified") or item.get("lastModified"),
        item.get("created"),
    ]

    parsed = []
    for x in candidates:
        if isinstance(x, str) and len(x) >= 4:
            d = parse_any_date(x)
            if d:
                parsed.append(d)

    if not parsed:
        return bool(keep_undated)

    dt = min(parsed)  # representative

    now = datetime.utcnow()
    if months:
        since_calc = now - timedelta(days=int(30.44 * months))
        until_calc = now
        return since_calc <= dt <= until_calc

    if since_dt and dt < since_dt:
        return False
    if until_dt and dt > until_dt:
        return False
    return True


# ---------- main ----------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="")
    ap.add_argument("--keep-undated", default="false", choices=["true", "false"])
    ap.add_argument("--include", default="")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--emit", default="list", choices=["list", "csv"])
    ap.add_argument("--out", default="")
    ap.add_argument("--max-items", type=int, default=0)
    ap.add_argument("--max-pages", type=int, default=None)  # ignored; compat
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    months = coerce_months(args.months)
    since_dt = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
    until_dt = datetime.strptime(args.until, "%Y-%m-%d") if args.until else None
    keep_undated = args.keep_undated.lower() == "true"

    include_set = set(x.strip().lower() for x in args.include.split(",") if x.strip())
    exclude_set = set(x.strip().lower() for x in args.exclude.split(",") if x.strip())

    sess = requests.Session()
    sess.headers.update(
        {"User-Agent": "RoadmapFetcher/1.6 (+https://github.com/ShannonBrayNC/m365-roadmap)"}
    )
    resp = sess.get(API, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if args.debug:
        print(f"[debug] total items from API: {len(data)}", file=sys.stderr)
        if data:
            print(f"[debug] sample keys: {sorted(data[0].keys())}", file=sys.stderr)
        # parseability stats
        parseable = 0
        for it in data:
            cands = [
                it.get("releaseDate"),
                it.get("publicPreviewDate"),
                it.get("rolloutStart"),
                it.get("publicDisclosureAvailabilityDate"),
                it.get("modified") or it.get("lastModified"),
                it.get("created"),
            ]
            any_dt = any(parse_any_date(x) for x in cands if isinstance(x, str))
            if any_dt:
                parseable += 1
        print(f"[debug] items with any parseable date: {parseable}", file=sys.stderr)

    out_items = []
    for item in data:
        if not instance_allowed(item, include_set, exclude_set):
            continue
        if not in_date_window(item, months, since_dt, until_dt, keep_undated=keep_undated):
            continue
        out_items.append(item)
        if args.max_items and len(out_items) >= args.max_items:
            break

    if args.debug:
        print(f"[debug] kept after filters: {len(out_items)}", file=sys.stderr)

    if args.emit == "csv":

        def write_csv(fh):
            w = csv.writer(fh)
            w.writerow(
                ["id", "title", "status", "phase", "targeted_dates", "cloud_instances", "link"]
            )
            for it in out_items:
                iid = it.get("id") or it.get("Id") or it.get("featureId") or ""
                title = it.get("title") or it.get("Title") or ""
                status = it.get("status") or it.get("Status") or it.get("publicRoadmapStatus") or ""

                # Phase may be list[str] or list[dict]
                phase = ""
                tc = it.get("tagsContainer") or it.get("TagsContainer") or {}
                phases = tc.get("releasePhase") or tc.get("ReleasePhase") or []
                if isinstance(phases, list) and phases:
                    first = phases[0]
                    if isinstance(first, dict):
                        phase = (
                            first.get("tagName") or first.get("name") or first.get("value") or ""
                        )
                    else:
                        phase = str(first)

                targeted = (
                    it.get("releaseDate")
                    or it.get("publicPreviewDate")
                    or it.get("rolloutStart")
                    or ""
                )

                clouds = instances_for(it)
                link = (
                    f"https://www.microsoft.com/microsoft-365/roadmap?featureid={iid}"
                    if iid
                    else ""
                )

                row = [
                    str(iid),
                    clean_text(title),
                    clean_text(status),
                    clean_text(phase),
                    clean_text(targeted),
                    ";".join(clouds),
                    link,
                ]
                w.writerow(row)

        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="") as fh:
                write_csv(fh)
        else:
            write_csv(sys.stdout)
    else:
        ids = []
        for it in out_items:
            iid = it.get("id") or it.get("Id") or it.get("featureId")
            if iid:
                ids.append(str(iid))
        print(",".join(ids))


if __name__ == "__main__":
    main()
