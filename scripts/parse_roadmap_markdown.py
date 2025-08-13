#!/usr/bin/env python3
import argparse
import csv
import json
import re
from datetime import datetime, timedelta

def parse_table(markdown_text):
    """Extracts table rows from Markdown."""
    lines = markdown_text.splitlines()
    table_started = False
    headers = []
    rows = []

    for line in lines:
        if "|" in line:
            parts = [cell.strip() for cell in line.strip().split("|") if cell.strip()]
            if not table_started:
                headers = parts
                table_started = True
            elif set(parts) != set(headers) and "---" not in line:
                rows.append(parts)

    return headers, rows

def filter_by_date(rows, headers, months, since, until):
    """Filter rows based on months, since, until criteria."""
    if not any([months, since, until]):
        return rows

    date_idx = headers.index("Targeted Release")
    filtered = []

    today = datetime.today()
    since_dt = datetime.strptime(since, "%Y-%m-%d") if since else None
    until_dt = datetime.strptime(until, "%Y-%m-%d") if until else None

    if months:
        until_dt = today + timedelta(days=int(months) * 30)
        since_dt = today

    for row in rows:
        try:
            date_str = row[date_idx]
            if not date_str or date_str.lower() == "tbd":
                continue
            date_obj = datetime.strptime(date_str, "%B %Y")  # e.g. "September 2025"
        except Exception:
            continue

        if since_dt and date_obj < since_dt:
            continue
        if until_dt and date_obj > until_dt:
            continue

        filtered.append(row)

    return filtered

def filter_by_instance(rows, headers, include, exclude):
    """Filter by cloud instance include/exclude lists."""
    if not include and not exclude:
        return rows

    instance_idx = headers.index("Cloud Instance")
    include_set = set([x.strip().lower() for x in include.split(",")]) if include else set()
    exclude_set = set([x.strip().lower() for x in exclude.split(",")]) if exclude else set()

    filtered = []
    for row in rows:
        instance_val = row[instance_idx].lower()

        if include_set and not any(inc in instance_val for inc in include_set):
            continue
        if exclude_set and any(exc in instance_val for exc in exclude_set):
            continue

        filtered.append(row)

    return filtered

def main():
    parser = argparse.ArgumentParser(description="Parse Microsoft 365 Roadmap Markdown to CSV/JSON")
    parser.add_argument("--input", required=True, help="Path to input Markdown file")
    parser.add_argument("--csv", required=True, help="Path to output CSV file")
    parser.add_argument("--json", required=True, help="Path to output JSON file")
    parser.add_argument("--months", required=False, help="Number of months forward to include")
    parser.add_argument("--since", required=False, help="Start date YYYY-MM-DD")
    parser.add_argument("--until", required=False, help="End date YYYY-MM-DD")
    parser.add_argument("--include", required=False, help="Comma-separated cloud instances to include")
    parser.add_argument("--exclude", required=False, help="Comma-separated cloud instances to exclude")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        md_content = f.read()

    headers, rows = parse_table(md_content)
    rows = filter_by_date(rows, headers, args.months, args.since, args.until)
    rows = filter_by_instance(rows, headers, args.include, args.exclude)

    # Write CSV
    with open(args.csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        writer.writerows(rows)

    # Write JSON
    json_data = [dict(zip(headers, row)) for row in rows]
    with open(args.json, "w", encoding="utf-8") as jsonfile:
        json.dump(json_data, jsonfile, indent=2, ensure_ascii=False)

    print(f"✅ Parsed {len(rows)} items from {args.input}")
    print(f"📄 CSV saved to {args.csv}")
    print(f"📄 JSON saved to {args.json}")

if __name__ == "__main__":
    main()
