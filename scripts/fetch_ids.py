#!/usr/bin/env python3
"""
Auto-discovers Microsoft 365 Roadmap feature IDs by scraping the public roadmap pages.

Key improvements vs prior version:
- Loose instance filtering: when include_set is present but the card's instance is missing,
  we KEEP the card (so we don't drop items whose instance isn't printed on the list page).
- Loose date filtering: when we can't parse the targeted date, we KEEP the card when any
  date filter is requested (post-processing will handle precise filtering from the final table).
- Debug logging and higher default pagination.

CLI:
  --months INT          Number of months back from today (1..6). Mutually exclusive with --since/--until
  --since YYYY-MM-DD    Start date
  --until YYYY-MM-DD    End date
  --include TEXT        Comma-separated cloud instances to include
  --exclude TEXT        Comma-separated instances to exclude
  --max-pages INT       Pagination cap (default 30)
  --emit TEXT           Output format: "csv" or "list" (default "list")
  --debug               Print discovery diagnostics

Output:
  Prints comma-separated IDs (list) OR CSV with columns:
    id,title,status,phase,targeted_dates,cloud_instance,link
"""

import argparse
import csv
import sys
import time
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.microsoft.com/en-us/microsoft-365/roadmap"

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=None)
    ap.add_argument("--since", type=str, default="")
    ap.add_argument("--until", type=str, default="")
    ap.add_argument("--include", type=str, default="")
    ap.add_argument("--exclude", type=str, default="")
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--emit", type=str, default="list", choices=["list", "csv"])
    ap.add_argument("--debug", action="store_true")
    return ap.parse_args()

def norm_instance(s: str) -> str:
    if not s: return ""
    t = s.strip().lower()
    if t in ("worldwide", "standard multi-tenant", "worldwide (standard multi-tenant)"):
        return "worldwide (standard multi-tenant)"
    if t in ("gcc high", "gcch"):
        return "gcc high"
    if t in ("us dod", "dod"):
        return "dod"
    if t in ("us gcc", "gcc"):
        return "gcc"
    return s.strip()

def within_date_loose(target_text: str, since_dt, until_dt, months) -> bool:
    """Loose date filter: if parsing fails or missing, KEEP the card when any date filter is requested."""
    # If no date filter requested, accept all
    if not (since_dt or until_dt or months):
        return True

    txt = (target_text or "").replace("CY", "").strip()
    if not txt or txt.lower() in ("tbd", "unknown", "n/a"):
        # Can't parse from list page -> keep it; post-processing will filter precisely later
        return True

    # Try standard formats
    for fmt in ("%B %Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(txt, fmt)
            return _dt_within(dt, since_dt, until_dt, months)
        except Exception:
            pass

    # Quarter
    m = re.match(r"^(Q[1-4])\s+(\d{4})$", txt, re.I)
    if m:
        q = m.group(1).upper()
        y = int(m.group(2))
        start_month = {"Q1":1,"Q2":4,"Q3":7,"Q4":10}[q]
        dt = datetime(y, start_month, 1)
        return _dt_within(dt, since_dt, until_dt, months)

    # Half
    m = re.match(r"^(H[12])\s+(\d{4})$", txt, re.I)
    if m:
        h = m.group(1).upper()
        y = int(m.group(2))
        start_month = {"H1":1,"H2":7}[h]
        dt = datetime(y, start_month, 1)
        return _dt_within(dt, since_dt, until_dt, months)

    # Year only
    m = re.match(r"^(\d{4})$", txt)
    if m:
        dt = datetime(int(m.group(1)), 1, 1)
        return _dt_within(dt, since_dt, until_dt, months)

    # Unparseable -> keep
    return True

def _dt_within(dt, since_dt, until_dt, months):
    now = datetime.utcnow()
    if months:
        # last N months up to today
        since_dt = now - timedelta(days=int(30.44*months))
        until_dt = now
    if since_dt and dt < since_dt: return False
    if until_dt and dt > until_dt: return False
    return True

def instance_allowed_loose(instance_text: str, include_set, exclude_set) -> bool:
    """Loose instance filter: if include_set is provided but instance is missing, KEEP item."""
    norm = norm_instance(instance_text).lower()
    if exclude_set and norm in exclude_set:
        return False
    if include_set:
        if not norm:
            return True  # keep unknowns; final filter will occur in post-processing
        return norm in include_set
    return True

def fetch_page(session, page: int):
    url = f"{BASE}?page={page}"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text

def parse_cards(html):
    """
    Parse feature cards out of a page.
    Returns list of dicts:
      id,title,status,phase,targeted_dates,cloud_instance,link
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for a in soup.select("a[href*='featureid=']"):
        href = a.get("href", "")
        m = re.search(r"featureid=(\d+)", href)
        if not m:
            continue
        fid = m.group(1)
        link = href if href.startswith("http") else urljoin(BASE, href)

        card = a.find_parent(["div","li","article"]) or a
        text = card.get_text(" ", strip=True)
        title = a.get_text(strip=True) or f"Feature {fid}"

        # Best-effort label extraction
        status = _extract_labeled(text, ["Status:", "status:"])
        phase = _extract_labeled(text, ["Release phase:", "Phase:", "release phase:"])
        targeted = _extract_labeled(text, ["Targeted:", "Targeted Release:", "Dates:", "Targeted dates:"])
        instance = _extract_labeled(text, ["Cloud instance:", "Instances:", "Cloud:", "Cloud Instance:"])

        cards.append({
            "id": fid,
            "title": title,
            "status": status,
            "phase": phase,
            "targeted_dates": targeted,
            "cloud_instance": instance,
            "link": link
        })
    return dedupe(cards, key="id")

def _extract_labeled(text, labels):
    for lab in labels:
        idx = text.lower().find(lab.lower())
        if idx != -1:
            seg = text[idx + len(lab):].strip()
            seg = seg.split("  ")[0].split("|")[0].split("  •  ")[0].strip()
            return seg
    return ""

def dedupe(items, key="id"):
    seen = set()
    out = []
    for it in items:
        k = it.get(key)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out

def main():
    args = parse_args()

    include_set = set(x.strip().lower() for x in args.include.split(",")) if args.include else set()
    exclude_set = set(x.strip().lower() for x in args.exclude.split(",")) if args.exclude else set()
    since_dt = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
    until_dt = datetime.strptime(args.until, "%Y-%m-%d") if args.until else None

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; RoadmapScraper/1.1; +https://example.local)"
    })

    all_cards = []
    for page in range(1, args.max_pages + 1):
        html = fetch_page(session, page)
        cards = parse_cards(html)
        if args.debug:
            print(f"[debug] page={page} cards_found={len(cards)}", file=sys.stderr)
        if not cards:
            break
        all_cards.extend(cards)
        time.sleep(0.6)  # be polite

    all_cards = dedupe(all_cards, key="id")

    # Apply loose filters
    filtered = []
    for c in all_cards:
        if not instance_allowed_loose(c.get("cloud_instance",""), include_set, exclude_set):
            continue
        if not within_date_loose(c.get("targeted_dates",""), since_dt, until_dt, args.months):
            continue
        filtered.append(c)

    if args.debug:
        print(f"[debug] total_cards={len(all_cards)} kept_after_filters={len(filtered)}", file=sys.stderr)

    if args.emit == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["id","title","status","phase","targeted_dates","cloud_instance","link"])
        for c in filtered:
            w.writerow([
                c.get("id",""),
                c.get("title",""),
                c.get("status",""),
                c.get("phase",""),
                c.get("targeted_dates",""),
                c.get("cloud_instance",""),
                c.get("link",""),
            ])
    else:
        print(",".join(c["id"] for c in filtered))

if __name__ == "__main__":
    main()
