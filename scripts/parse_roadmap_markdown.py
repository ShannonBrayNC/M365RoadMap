#!/usr/bin/env python3
from __future__ import annotations

# Allows `python scripts/parse_roadmap_markdown.py` from repo root
try:
    from scripts import _importlib_local  # noqa: F401
except Exception:
    pass

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from scripts.report_templates import CLOUD_LABELS, normalize_clouds, parse_date_soft


# Strict markers that must match generator output
H_FEATURE = re.compile(r"^##\s*\[(?P<id>[^\]]+)\]\s*(?P<title>.+?)\s*$")
H_SUMMARY = re.compile(r"^###\s*Summary\s*$", re.I)
H_CHANGING = re.compile(r"^###\s*What’s changing\s*$", re.I)
H_IMPACT = re.compile(r"^###\s*Impact and rollout\s*$", re.I)
H_ACTIONS = re.compile(r"^###\s*Action items\s*$", re.I)

META_PATTERNS = {
    "Product/Workload": re.compile(r"^\*\*Product/Workload:\*\*\s*(?P<val>.*)$"),
    "Status": re.compile(r"^\*\*Status:\*\*\s*(?P<val>.*)$"),
    "Cloud(s)": re.compile(r"^\*\*Cloud\(s\):\*\*\s*(?P<val>.*)$"),
    "Last Modified": re.compile(r"^\*\*Last Modified:\*\*\s*(?P<val>.*)$"),
    "Release Date": re.compile(r"^\*\*Release Date:\*\*\s*(?P<val>.*)$"),
    "Source": re.compile(r"^\*\*Source:\*\*\s*(?P<val>.*)$"),
    "Message ID": re.compile(r"^\*\*Message ID:\*\*\s*(?P<val>.*)$"),
    "Official Roadmap": re.compile(r"^\*\*Official Roadmap:\*\*\s*(?P<val>.*)$"),
}


def months_to_dt_utc_approx(months: int) -> dt.datetime:
    days = max(1, int(months) * 30)
    return dt.datetime.utcnow() - dt.timedelta(days=days)


def parse_features(md_text: str) -> List[Dict[str, str]]:
    lines = md_text.splitlines()
    i = 0
    n = len(lines)
    out: List[Dict[str, str]] = []

    while i < n:
        m = H_FEATURE.match(lines[i])
        if not m:
            i += 1
            continue

        # Start of a feature
        cur: Dict[str, str] = {
            "PublicId": m.group("id").strip(),
            "Title": m.group("title").strip(),
            "Product_Workload": "",
            "Status": "",
            "LastModified": "",
            "ReleaseDate": "",
            "Cloud_instance": "",
            "Official_Roadmap_link": "",
            "Source": "",
            "MessageId": "",
            # Narrative fields
            "Summary": "",
            "WhatsChanging": "",
            "ImpactAndRollout": "",
            "ActionItems": "",
        }
        i += 1

        # Read meta block (bold label lines) until a blank + a "### ..." section
        while i < n and lines[i].strip():
            matched_any = False
            for key, pat in META_PATTERNS.items():
                mm = pat.match(lines[i])
                if mm:
                    val = mm.group("val").strip()
                    if key == "Product/Workload":
                        cur["Product_Workload"] = val
                    elif key == "Status":
                        cur["Status"] = val
                    elif key == "Cloud(s)":
                        cur["Cloud_instance"] = val
                    elif key == "Last Modified":
                        cur["LastModified"] = val
                    elif key == "Release Date":
                        cur["ReleaseDate"] = val
                    elif key == "Source":
                        cur["Source"] = val
                    elif key == "Message ID":
                        cur["MessageId"] = val
                    elif key == "Official Roadmap":
                        cur["Official_Roadmap_link"] = val
                    matched_any = True
                    break
            if not matched_any:
                break  # meta block ended
            i += 1

        # Skip possible single blank line
        if i < n and not lines[i].strip():
            i += 1

        # Section bodies until next feature or EOF
        def read_section() -> str:
            nonlocal i
            buf: List[str] = []
            while i < n and not H_FEATURE.match(lines[i]) and not H_SUMMARY.match(lines[i]) and not H_CHANGING.match(lines[i]) and not H_IMPACT.match(lines[i]) and not H_ACTIONS.match(lines[i]):
                buf.append(lines[i])
                i += 1
            return "\n".join(buf).strip()

        while i < n and not H_FEATURE.match(lines[i]):
            if H_SUMMARY.match(lines[i]):
                i += 1
                cur["Summary"] = read_section()
            elif H_CHANGING.match(lines[i]):
                i += 1
                cur["WhatsChanging"] = read_section()
            elif H_IMPACT.match(lines[i]):
                i += 1
                cur["ImpactAndRollout"] = read_section()
            elif H_ACTIONS.match(lines[i]):
                i += 1
                cur["ActionItems"] = read_section()
            else:
                # Unexpected line inside feature; consume it to avoid infinite loop
                i += 1

        out.append(cur)

    return out


def write_csv_json(
    rows: List[Dict[str, str]],
    csv_path: Optional[Path],
    json_path: Optional[Path],
) -> None:
    if not rows:
        # Still write empty skeleton so downstream steps don't blow up
        headers = [
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
            "Summary",
            "WhatsChanging",
            "ImpactAndRollout",
            "ActionItems",
        ]
        if csv_path:
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow(headers)
            print("No data to write to CSV.")
        if json_path:
            json_path.write_text("[]", encoding="utf-8")
        return

    headers = list(rows[0].keys())
    if csv_path:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            w.writerows(rows)
        print(f"CSV written to {csv_path}")
    if json_path:
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON written to {json_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Markdown input produced by generate_report.py")
    ap.add_argument("--csv", default="", help="Optional CSV output")
    ap.add_argument("--json", default="", help="Optional JSON output")
    ap.add_argument("--months", type=int, default=None, help="Optional lookback months")
    ap.add_argument("--since", default="", help="Optional YYYY-MM-DD lower bound (overrides months)")
    args = ap.parse_args()

    src = Path(args.input)
    md_text = src.read_text(encoding="utf-8")

    feats = parse_features(md_text)

    # Filter by dates if requested (based on LastModified)
    since_dt: Optional[dt.datetime] = None
    if args.months is not None:
        since_dt = months_to_dt_utc_approx(args.months)
    if args.since:
        try:
            since_dt = dt.datetime.strptime(args.since.strip(), "%Y-%m-%d")
        except Exception:
            pass

    if since_dt is not None:
        feats = [
            r
            for r in feats
            if (parse_date_soft(r.get("LastModified", "")) or dt.datetime.min) >= since_dt
        ]

    csv_path = Path(args.csv) if args.csv else None
    json_path = Path(args.json) if args.json else None
    write_csv_json(feats, csv_path, json_path)


if __name__ == "__main__":
    main()
