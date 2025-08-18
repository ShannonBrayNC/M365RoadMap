#!/usr/bin/env python3
"""
M365 Roadmap + Message Center enricher

Purpose
-------
Given a master file (CSV or JSON) containing Microsoft 365 Roadmap items
(with columns like PublicId, MessageId, Official_Roadmap_link), this script:
  1) Fetches the corresponding Message Center page (via the public mirror
     at https://mc.merill.net) for each MCxxxxx ID.
  2) Fetches the official Roadmap page for each Roadmap ID (PublicId), when present.
  3) Parses and extracts: Cloud(s), Release Date, Summary, What's changing,
     Impact and rollout, Action items.
  4) Merges the new fields into an enriched dataset and writes CSV + JSON.

Notes
-----
* The Message Center admin portal requires tenant auth; this script uses the
  public mirror (mc.merill.net). Parsing is resilient to common format changes.
* Use this script interactively or as a CLI tool.

Usage
-----
python m365_enrich.py \
  --input /path/to/roadmap_report_master.json \
  --out-json /path/to/roadmap_report_enriched.json \
  --out-csv  /path/to/roadmap_report_enriched.csv

Dependencies
------------
- requests
- beautifulsoup4
- pandas

Install with:
  pip install -r requirements.txt

"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

# --------------------------- Config -----------------------------------------
MC_MIRROR_BASE = "https://mc.merill.net/mc/"
ROADMAP_SEARCH_BASE = (
    "https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms="
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

REQUEST_TIMEOUT = 20
RETRY_COUNT = 3
BACKOFF_SEC = 1.5
PARALLEL_WORKERS = 6

# ------------------------ Helpers & Parsers ---------------------------------


def _get(url: str) -> Optional[str]:
    """HTTP GET with simple retry/backoff, return text or None."""
    headers = {"User-Agent": USER_AGENT}
    last_exc = None
    for i in range(RETRY_COUNT):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200 and resp.text:
                return resp.text
        except Exception as e:  # noqa: BLE001
            last_exc = e
        time.sleep(BACKOFF_SEC * (i + 1))
    if last_exc:
        sys.stderr.write(f"GET failed for {url}: {last_exc}\n")
    else:
        sys.stderr.write(f"GET failed for {url}: status {resp.status_code}\n")
    return None


def fetch_mc_html(message_id: str) -> Optional[str]:
    mid = message_id.strip().upper()
    if not re.match(r"MC\d{6,7}", mid):
        return None
    url = MC_MIRROR_BASE + mid
    return _get(url)


def fetch_roadmap_html(roadmap_id: str) -> Optional[str]:
    rid = roadmap_id.strip()
    if not rid:
        return None
    url = ROADMAP_SEARCH_BASE + requests.utils.quote(rid)
    return _get(url)


def _clean_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t


def parse_mc(html: str) -> Dict[str, str]:
    """Parse Message Center HTML from mc.merill.net and extract fields.
    Returns keys: Summary, Whats_changing, Impact_and_rollout, Action_items, Clouds, Release_Date
    """
    out = {
        k: ""
        for k in [
            "Summary",
            "Whats_changing",
            "Impact_and_rollout",
            "Action_items",
            "Clouds",
            "Release_Date",
        ]
    }
    if not html:
        return out

    soup = BeautifulSoup(html, "html.parser")

    # Summary: often first paragraph(s) under the title or a section called "Message Summary" / "Message summary"
    # Try several heuristics:
    title = soup.find(["h1", "h2"])
    first_p = soup.find("p")
    if first_p:
        out["Summary"] = _clean_text(first_p.get_text(" "))

    # Look for headings that commonly appear in MC pages
    section_map = {
        "Whats_changing": [
            "What's changing",
            "What’s changing",
            "What is changing",
            "Changes",
            "Overview",
        ],
        "Impact_and_rollout": [
            "When this will happen",
            "Rollout",
            "Roll-out",
            "Impact",
            "Timing",
            "Rollout schedule",
        ],
        "Action_items": [
            "What you need to do",
            "Action required",
            "Next steps",
            "Prepare",
            "What you can do to prepare",
        ],
    }

    def find_section_text(aliases: List[str]) -> str:
        for header_tag in soup.find_all(re.compile("^h[1-4]$")):
            txt = _clean_text(header_tag.get_text(" "))
            for alias in aliases:
                if alias.lower() in txt.lower():
                    parts = []
                    for sib in header_tag.find_all_next(limit=30):
                        if sib.name and re.match(r"^h[1-4]$", sib.name, re.I):
                            break
                        if sib.name in ("p", "li"):
                            parts.append(_clean_text(sib.get_text(" ")))
                    return " \n".join([p for p in parts if p])
        return ""

    for key, aliases in section_map.items():
        out[key] = find_section_text(aliases)

    # Try to detect Clouds and Release timeline words from the whole page
    full_text = _clean_text(soup.get_text(" "))

    # Clouds
    clouds = []
    cloud_keywords = [
        ("Worldwide", r"Worldwide"),
        ("GCC", r"GCC(?! High|\s*High)"),
        ("GCC High", r"GCC\s*High"),
        ("DoD", r"DoD"),
        ("Education", r"Education"),
        ("Sovereign", r"Sovereign|EU Data Boundary"),
    ]
    for label, pat in cloud_keywords:
        if re.search(pat, full_text, flags=re.I):
            clouds.append(label)
    if clouds:
        out["Clouds"] = ", ".join(dict.fromkeys(clouds))

    # Release date: capture common phrases like "mid–Aug 2025", "June 2025", ranges
    date_match = re.search(
        r"((early|mid|late)[ -–])?(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+20\d{2}([^\.;)]{0,30})?",
        full_text,
        re.I,
    )
    if date_match:
        out["Release_Date"] = _clean_text(date_match.group(0))

    return out


def parse_roadmap(html: str) -> Dict[str, str]:
    """Parse Roadmap item search page for Clouds and Release hints.
    This is heuristic because the Roadmap page renders client-side; we fall back
    to scanning the static HTML for descriptive text including cloud names/months.
    """
    out = {"Clouds": "", "Release_Date": ""}
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    text = _clean_text(soup.get_text(" "))

    # Clouds detection
    clouds = []
    for label in ["Worldwide", "GCC High", "GCC", "DoD", "Education", "Sovereign"]:
        if re.search(rf"\b{re.escape(label)}\b", text, re.I):
            clouds.append(label)
    if clouds:
        out["Clouds"] = ", ".join(dict.fromkeys(clouds))

    # Release month/year detection in the page text
    m = re.search(
        r"(Preview|GA|General Availability|Rollout)[:\s-]+((early|mid|late)[ -–])?(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+20\d{2}",
        text,
        re.I,
    )
    if m:
        out["Release_Date"] = _clean_text(m.group(0))
    else:
        m2 = re.search(
            r"(\bJan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+20\d{2}",
            text,
            re.I,
        )
        if m2:
            out["Release_Date"] = _clean_text(m2.group(0))

    return out


def enrich_row(row: Dict[str, str]) -> Dict[str, str]:
    msg_id = (row.get("MessageId") or "").strip()
    roadmap_id = (row.get("PublicId") or "").strip()

    mc_data = {}
    if msg_id:
        html = fetch_mc_html(msg_id)
        if html:
            mc_data = parse_mc(html)

    roadmap_data = {}
    if roadmap_id:
        rhtml = fetch_roadmap_html(roadmap_id)
        if rhtml:
            roadmap_data = parse_roadmap(rhtml)

    # Merge preference: narrative fields from MC, Clouds/Release prefer MC then Roadmap
    enriched = {
        "Clouds": mc_data.get("Clouds")
        or roadmap_data.get("Clouds")
        or row.get("Cloud_instance", ""),
        "Release_Date": mc_data.get("Release_Date")
        or roadmap_data.get("Release_Date")
        or row.get("ReleaseDate", ""),
        "Summary": mc_data.get("Summary", ""),
        "Whats_changing": mc_data.get("Whats_changing", ""),
        "Impact_and_rollout": mc_data.get("Impact_and_rollout", ""),
        "Action_items": mc_data.get("Action_items", ""),
    }

    return enriched


def run(input_path: str, out_json: str, out_csv: str) -> Tuple[pd.DataFrame, int]:
    # Load master
    if input_path.lower().endswith(".json"):
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        df = pd.DataFrame(data)
    else:
        df = pd.read_csv(input_path)

    # Ensure columns exist
    for col in [
        "Clouds",
        "Release_Date",
        "Summary",
        "Whats_changing",
        "Impact_and_rollout",
        "Action_items",
    ]:
        if col not in df.columns:
            df[col] = ""

    rows = df.to_dict(orient="records")

    def _task(idx_row):
        i, r = idx_row
        try:
            enr = enrich_row(r)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"enrich failed for row {i}: {e}\n")
            enr = {
                k: r.get(k, "")
                for k in [
                    "Clouds",
                    "Release_Date",
                    "Summary",
                    "Whats_changing",
                    "Impact_and_rollout",
                    "Action_items",
                ]
            }
        return i, enr

    with cf.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        for i, enr in ex.map(_task, enumerate(rows)):
            for k, v in enr.items():
                if v and (pd.isna(df.at[i, k]) or not str(df.at[i, k]).strip()):
                    df.at[i, k] = v

    # Save
    df.to_json(out_json, orient="records", indent=2, force_ascii=False)
    df.to_csv(out_csv, index=False, encoding="utf-8")

    return df, len(df)


def main():
    ap = argparse.ArgumentParser(
        description="Enrich M365 Roadmap items with Message Center + Roadmap data"
    )
    ap.add_argument(
        "--input", required=True, help="Path to roadmap_report_master.(json|csv)"
    )
    ap.add_argument("--out-json", required=True, help="Output enriched JSON path")
    ap.add_argument("--out-csv", required=True, help="Output enriched CSV path")
    args = ap.parse_args()

    df, n = run(args.input, args.out_json, args.out_csv)
    print(
        f"Enriched {n} rows. Written to:\n  JSON: {args.out_json}\n  CSV : {args.out_csv}"
    )


if __name__ == "__main__":
    main()

# ----------------------------- requirements.txt -----------------------------
# Place the following lines into a separate file named requirements.txt if needed:
# requests
# beautifulsoup4
# pandas
