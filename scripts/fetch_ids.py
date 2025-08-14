#!/usr/bin/env python3
"""
fetch_ids.py v1.5 — Microsoft 365 Roadmap ID discovery (JSON API)

- Backward-compatible flags:
    * accepts --max-pages (ignored), to tolerate older workflows
    * accepts --months "" (blank) and coerces safely
    * supports --out PATH for CSV
- Always writes UTF-8 (Windows friendly)
- Filters loosely by dates and cloud instances

Endpoint:
  https://www.microsoft.com/releasecommunications/api/v1/m365
"""

import argparse
import csv
import sys
from datetime import datetime, timedelta

import requests

API = "https://www.microsoft.com/releasecommunications/api/v1/m365"

# Force UTF-8 stdout (Windows-safe)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
    return t

def parse_isoish(dt_str: str | None):
    if not dt_str:
        return None
    fmts = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ")
    for fmt in fmts:
        try:
            return datetime.strptime(dt_str[:len(fmt)], fmt)
        except Exception:
            pass
    return None

def in_date_window(item, months, since_dt, until_dt):
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
    parsed = [parse_isoish(x) for x in candidates if isinstance(x, str) and len(x) >= 4]
    parsed = [p for p in parsed if p is not None]
    if not parsed:
        return True
    dt = min(parsed)
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

def instances_for(item):
    tc = item.get("tagsContainer") or item.get("TagsContainer") or {}
    vals = tc.get("cloudInstances") or tc.get("CloudInstances") or []
    if not vals:
        tags = item.get("tags") or item.get("Tags") or []
        vals = [t for t in tags if isinstance(t, str) and any(k in t.lower() for k in ("gcc", "dod", "worldwide"))]
    return [norm_instance(v) for v in vals if isinstance(v, str)]

def instance_allowed(item, include_set, exclude_set):
    vals = instances_for(item)
    if exclude_set and any(v in exclude_set for v in vals):
        return False
    if include_set:
        if not vals:  # keep unknowns; final report can filter later
            return True
        return any(v in include_set for v in vals)
    return True

def main():
    ap = argparse.ArgumentParser()
    # note: months is str to allow "", then we coerce
    ap.add_argument("--months", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="")
    ap.add_argument("--include", default="")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--emit", default="list", choices=["list", "csv"])
    ap.add_argument("--out", default="")
    ap.add_argument("--max-items", type=int, default=0)
    # backward compat: accept --max-pages but ignore it
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    months = coerce_months(args.months)
    since_dt = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
    until_dt = datetime.strptime(args.until, "%Y-%m-%d") if args.until else None

    include_set = set(x.strip().lower() for x in args.include.split(",") if x.strip())
    exclude_set = set(x.strip().lower() for x in args.exclude.split(",") if x.strip())

    sess = requests.Session()
    sess.headers.update({"User-Agent": "RoadmapFetcher/1.5 (+https://github.com/your-org/your-repo)"})
    resp = sess.get(API, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if args.debug:
        print(f"[debug] total items from API: {len(data)}", file=sys.stderr)
        if data:
            print(f"[debug] sample keys: {sorted(data[0].keys())}", file=sys.stderr)

    out_items = []
    for item in data:
        if not instance_allowed(item, include_set, exclude_set):
            continue
        if not in_date_window(item, months, since_dt, until_dt):
            continue
        out_items.append(item)
        if args.max_items and len(out_items) >= args.max_items:
            break

    if args.debug:
        print(f"[debug] kept after filters: {len(out_items)}", file=sys.stderr)

    if args.emit == "csv":
        def write_csv(fh):
            w = csv.writer(fh)
            w.writerow(["id","title","status","phase","targeted_dates","cloud_instances","link"])
            for it in out_items:
                iid = it.get("id") or it.get("Id") or it.get("featureId") or ""
                title = it.get("title") or it.get("Title") or ""
                status = it.get("status") or it.get("Status") or it.get("publicRoadmapStatus") or ""
                phase = ""
                tc = it.get("tagsContainer") or it.get("TagsContainer") or {}
                phases = tc.get("releasePhase") or tc.get("ReleasePhase") or []
                if isinstance(phases, list) and phases:
                    phase = phases[0]
                targeted = it.get("releaseDate") or it.get("publicPreviewDate") or it.get("rolloutStart") or ""
                clouds = instances_for(it)
                link = f"https://www.microsoft.com/microsoft-365/roadmap?featureid={iid}" if iid else ""
                w.writerow([iid, title, status, phase, targeted, ";".join(clouds), link])

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
