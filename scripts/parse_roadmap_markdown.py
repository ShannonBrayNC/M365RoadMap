import argparse
import csv
import json
import re
from datetime import datetime, timedelta

def parse_table(md_lines):
    """Parse a Markdown table into a list of dicts."""
    table_lines = []
    for line in md_lines:
        if line.strip().startswith("|"):
            table_lines.append(line.strip())
        elif table_lines:
            # break if we already started capturing table and hit a non-table line
            break

    if not table_lines:
        return []

    headers = [h.strip() for h in table_lines[0].strip("|").split("|")]
    rows = []
    for row_line in table_lines[2:]:  # skip header + separator
        cols = [c.strip() for c in row_line.strip("|").split("|")]
        # pad columns if needed
        while len(cols) < len(headers):
            cols.append("")
        rows.append(dict(zip(headers, cols)))

    return rows

def filter_by_dates(rows, months=None, since=None, until=None):
    """Filter rows based on date window."""
    if not months and not since and not until:
        return rows

    def parse_date(date_str):
        try:
            return datetime.strptime(date_str.strip(), "%B %Y")
        except ValueError:
            try:
                return datetime.strptime(date_str.strip(), "%B %d, %Y")
            except ValueError:
                return None

    now = datetime.utcnow()
    if months:
        since_date = now
        until_date = now + timedelta(days=int(months) * 30)
    else:
        since_date = datetime.strptime(since, "%Y-%m-%d") if since else None
        until_date = datetime.strptime(until, "%Y-%m-%d") if until else None
        if since_date and not until_date:
            until_date = since_date + timedelta(days=180)

    filtered = []
    for row in rows:
        date_field = None
        for key in row:
            if "date" in key.lower():
                date_field = row[key]
                break
        if not date_field:
            filtered.append(row)
            continue

        parsed = parse_date(date_field)
        if not parsed:
            filtered.append(row)
            continue

        if since_date and parsed < since_date:
            continue
        if until_date and parsed > until_date:
            continue

        filtered.append(row)

    return filtered

def filter_by_instances(rows, include=None, exclude=None):
    """Filter rows based on Cloud Instance column."""
    if not include and not exclude:
        return rows

    include_set = {i.strip().lower() for i in include.split(",")} if include else set()
    exclude_set = {i.strip().lower() for i in exclude.split(",")} if exclude else set()

    filtered = []
    for row in rows:
        instance_val = ""
        for key in row:
            if "instance" in key.lower():
                instance_val = row[key]
                break
        normalized = instance_val.strip().lower()

        if include_set and normalized not in include_set:
            continue
        if exclude_set and normalized in exclude_set:
            continue

        filtered.append(row)

    return filtered

def main():
    parser = argparse.ArgumentParser(description="Parse Roadmap Master Summary Table from Markdown and export CSV/JSON.")
    parser.add_argument("--in", dest="infile", required=True, help="Input Markdown file")
    parser.add_argument("--csv", help="Output CSV file")
    parser.add_argument("--json", help="Output JSON file")
    parser.add_argument("--months", type=int, help="Number of months forward from now to include")
    parser.add_argument("--since", help="Start date in YYYY-MM-DD format")
    parser.add_argument("--until", help="End date in YYYY-MM-DD format")
    parser.add_argument("--include-instances", help="Comma-separated list of instances to include")
    parser.add_argument("--exclude-instances", help="Comma-separated list of instances to exclude")
    args = parser.parse_args()

    with open(args.infile, encoding="utf-8") as f:
        lines = f.readlines()

    # find the "Master Summary Table"
    start_idx = None
    for i, line in enumerate(lines):
        if "master summary table" in line.lower():
            start_idx = i
            break

    if start_idx is None:
        print("No Master Summary Table heading found.")
        return

    rows = parse_table(lines[start_idx+1:])
    if not rows:
        print("No table found under Master Summary Table heading.")
        return

    # filter
    rows = filter_by_dates(rows, args.months, args.since, args.until)
    rows = filter_by_instances(rows, args.include_instances, args.exclude_instances)

    # output CSV
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    # output JSON
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)

    print(f"Parsed {len(rows)} rows.")

if __name__ == "__main__":
    main()
