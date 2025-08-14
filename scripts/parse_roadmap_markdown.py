import argparse
import csv
import json
import os
import re
from datetime import datetime
from typing import List, Dict, Optional


def parse_markdown(md_text: str, months: Optional[int] = None) -> List[Dict[str, str]]:
    rows = []
    current_row = {}
    lines = md_text.splitlines()

    def flush_row():
        nonlocal current_row
        if current_row:
            rows.append(current_row)
            current_row = {}

    for line in lines:
        line = line.strip()
        if line.startswith("**Feature ID:**"):
            flush_row()
            current_row["Feature ID"] = line.split("**Feature ID:**", 1)[1].strip()
        elif line.startswith("**Title:**"):
            current_row["Title"] = line.split("**Title:**", 1)[1].strip()
        elif line.startswith("**Description:**"):
            current_row["Description"] = line.split("**Description:**", 1)[1].strip()
        elif line.startswith("**Added to Roadmap:**"):
            date_str = line.split("**Added to Roadmap:**", 1)[1].strip()
            current_row["Added to Roadmap"] = date_str
            if months:
                try:
                    date_obj = datetime.strptime(date_str, "%B %Y")
                    cutoff = datetime.now().replace(day=1)
                    cutoff_months = cutoff.month - months
                    cutoff_year = cutoff.year
                    while cutoff_months <= 0:
                        cutoff_months += 12
                        cutoff_year -= 1
                    cutoff_date = datetime(cutoff_year, cutoff_months, 1)
                    if date_obj < cutoff_date:
                        current_row = {}
                except ValueError:
                    pass
        elif line.startswith("**Last Modified:**"):
            current_row["Last Modified"] = line.split("**Last Modified:**", 1)[1].strip()
        elif line.startswith("**Tags:**"):
            current_row["Tags"] = line.split("**Tags:**", 1)[1].strip()
        elif line.startswith("**Category:**"):
            current_row["Category"] = line.split("**Category:**", 1)[1].strip()
        elif line.startswith("**Release Phase:**"):
            current_row["Release Phase"] = line.split("**Release Phase:**", 1)[1].strip()
        elif line.startswith("**Release Date:**"):
            current_row["Release Date"] = line.split("**Release Date:**", 1)[1].strip()

    flush_row()
    return rows


def write_csv(rows: List[Dict[str, str]], path: str) -> None:
    if not rows:
        print("No data to write to CSV.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: List[Dict[str, str]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse M365 Roadmap Markdown to CSV/JSON (with optional RSS/JSON fallback)")
    ap.add_argument("--input", required=True, help="Input Markdown file path")
    ap.add_argument("--csv", help="Output CSV path")
    ap.add_argument("--json", help="Output JSON path")
    ap.add_argument("--months", type=int, default=None, help="Filter to last N months (1..24)")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input file not found: {args.input}")

    with open(args.input, "r", encoding="utf-8") as f:
        md_text = f.read()

    rows = parse_markdown(md_text, months=args.months)

    if args.csv:
        write_csv(rows, args.csv)
        print(f"CSV written to {args.csv}")
    if args.json:
        write_json(rows, args.json)
        print(f"JSON written to {args.json}")


if __name__ == "__main__":
    main()
