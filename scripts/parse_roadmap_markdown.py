import sys
import pandas as pd
from datetime import datetime, timedelta

def filter_by_date(rows, headers, months, since, until):
    if not any([months, since, until]):
        return rows

    date_idx = None
    for i, h in enumerate(headers):
        if "release" in h.lower() or "date" in h.lower():
            date_idx = i
            break
    if date_idx is None:
        print("⚠️ No release/date column found, skipping date filtering.")
        return rows

    filtered = []
    today = datetime.today()
    since_dt = datetime.strptime(since, "%Y-%m-%d") if since else None
    until_dt = datetime.strptime(until, "%Y-%m-%d") if until else None

    if months:
        since_dt = today
        until_dt = today + timedelta(days=int(months) * 30)

    for row in rows:
        try:
            date_str = row[date_idx].replace("CY", "").strip()
            if not date_str or date_str.lower() == "tbd":
                continue
            date_obj = datetime.strptime(date_str, "%B %Y")
        except Exception:
            continue

        if since_dt and date_obj < since_dt:
            continue
        if until_dt and date_obj > until_dt:
            continue
        filtered.append(row)

    return filtered

def main():
    if len(sys.argv) != 9:
        print("Usage: parse_roadmap_markdown.py input.md output.csv output.json months since until include exclude")
        sys.exit(1)

    input_file, csv_file, json_file, months, since, until, include, exclude = sys.argv[1:]
    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find table
    table_lines = [l.strip() for l in lines if "|" in l and "---" not in l]
    headers = [h.strip() for h in table_lines[0].split("|") if h.strip()]
    rows = [[c.strip() for c in l.split("|") if c.strip()] for l in table_lines[1:]]

    # Date filtering
    rows = filter_by_date(rows, headers, months, since, until)

    # Include/exclude filtering
    if include:
        rows = [r for r in rows if any(inc in " ".join(r) for inc in include.split(","))]
    if exclude:
        rows = [r for r in rows if not any(exc in " ".join(r) for exc in exclude.split(","))]

    df = pd.DataFrame(rows, columns=headers)
    df.to_csv(csv_file, index=False)
    df.to_json(json_file, orient="records", indent=2)
    print(f"✅ CSV saved to {csv_file}")
    print(f"✅ JSON saved to {json_file}")

if __name__ == "__main__":
    main()
