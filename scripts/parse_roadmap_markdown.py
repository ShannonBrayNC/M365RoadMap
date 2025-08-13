#!/usr/bin/env python3
import argparse
import csv
import json
import re
from datetime import datetime, timedelta

# ---------- table parsing ----------

SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

def split_row(s: str):
    s = s.strip()
    if s.startswith("|"): s = s[1:]
    if s.endswith("|"): s = s[:-1]
    parts = [c.strip() for c in s.split("|")]
    # drop fully empty trailing cells caused by accidental final pipe
    while parts and parts[-1] == "":
        parts.pop()
    return parts

def find_first_table(lines):
    """
    Find the first markdown pipe table: a header line containing '|',
    immediately followed by a separator line like |---|---|.
    Returns (header_line_index, sep_line_index).
    """
    n = len(lines)
    for i in range(n - 1):
        line = lines[i].rstrip("\n")
        nxt = lines[i + 1].rstrip("\n")
        if "|" in line and SEP_RE.match(nxt or ""):
            return i, i + 1
    return None, None

def parse_first_table(md_text):
    """
    Parse the first markdown pipe table in the text.
    Returns headers (list[str]) and rows (list[list[str]]).
    """
    lines = md_text.splitlines()
    h_idx, s_idx = find_first_table(lines)
    if h_idx is None:
        raise RuntimeError("No markdown table (with |---| separator) found.")

    header_line = lines[h_idx]
    headers = [h for h in split_row(header_line) if h != ""]
    rows = []

    # Collect row lines until a non-table line
    for j in range(s_idx + 1, len(lines)):
        ln = lines[j].rstrip("\n")
        if not ln.strip().startswith("|"):
            # stop when table ends
            if rows:  # only break if we've already started collecting rows
                break
            # if there are blank lines between header and first row, skip them
            if ln.strip() == "":
                continue
            else:
                break
        if SEP_RE.match(ln):
            continue  # skip accidental extra separator lines
        row = split_row(ln)
        rows.append(row)

    # Fallbacks if header was malformed (e.g., only 1 cell)
    max_cols = max((len(r) for r in rows), default=len(headers))
    if len(headers) < 2 and max_cols > 1:
        # Try to infer headers from first row if it looks header-ish (e.g., text-only)
        inferred = []
        if rows:
            inferred = [f"Col {i+1}" for i in range(len(rows[0]))]
        if inferred and len(inferred) == max_cols:
            headers = inferred
        else:
            headers = [f"Col {i+1}" for i in range(max_cols)]

    # Normalize all rows to header width
    norm_rows = []
    for r in rows:
        if len(r) < len(headers):
            r = r + [""] * (len(headers) - len(r))
        elif len(r) > len(headers):
            r = r[:len(headers)]
        norm_rows.append(r)

    return headers, norm_rows

# ---------- filtering helpers ----------

def flexible_date_index(headers):
    for i, h in enumerate(headers):
        hl = h.lower()
        if "targeted" in hl and "date" in hl:
            return i
    for i, h in enumerate(headers):
        hl = h.lower()
        if "release" in hl or "date" in hl or "window" in hl:
            return i
    return None

def normalize_date_cell(s):
    if not s: return None
    text = s.strip().replace("CY", "").strip()
    # Month Year
    for fmt in ("%B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    # Quarter
    m = re.match(r"^(Q[1-4])\s+(\d{4})$", text, re.I)
    if m:
        q = m.group(1).upper()
        y = int(m.group(2))
        start_month = {"Q1":1,"Q2":4,"Q3":7,"Q4":10}[q]
        return datetime(y, start_month, 1)
    # Half
    m = re.match(r"^(H[12])\s+(\d{4})$", text, re.I)
    if m:
        h = m.group(1).upper()
        y = int(m.group(2))
        start_month = {"H1":1,"H2":7}[h]
        return datetime(y, start_month, 1)
    # Year only
    m = re.match(r"^(\d{4})$", text)
    if m:
        return datetime(int(m.group(1)), 1, 1)
    return None

def filter_by_date(rows, headers, months, since, until):
    if not any([months, since, until]):
        return rows

    idx = flexible_date_index(headers)
    if idx is None:
        print("⚠️ No release/date column found, skipping date filtering.")
        return rows

    today = datetime.utcnow()
    since_dt = datetime.strptime(since, "%Y-%m-%d") if since else None
    until_dt = datetime.strptime(until, "%Y-%m-%d") if until else None
    if months:
        try:
            n = int(months)
            if 1 <= n <= 6:
                since_dt = today - timedelta(days=int(30.44 * n))
                until_dt = today
        except Exception:
            pass

    out = []
    for r in rows:
        dtv = normalize_date_cell(r[idx] if idx < len(r) else "")
        if dtv is None:
            # Keep rows with unparseable/TBD dates; they’ll still show in CSV/JSON
            out.append(r)
            continue
        if since_dt and dtv < since_dt:
            continue
        if until_dt and dtv > until_dt:
            continue
        out.append(r)
    return out

def filter_by_instance(rows, headers, include, exclude):
    inst_idx = None
    for i, h in enumerate(headers):
        hl = h.lower()
        if "cloud instance" in hl or "instance" in hl:
            inst_idx = i
            break
    if inst_idx is None:
        return rows

    inc = set(x.strip().lower() for x in include.split(",")) if include else set()
    exc = set(x.strip().lower() for x in exclude.split(",")) if exclude else set()

    def norm(s):
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
        return t

    out = []
    for r in rows:
        nv = norm(r[inst_idx] if inst_idx < len(r) else "")
        if inc and nv not in inc:
            continue
        if exc and nv in exc:
            continue
        out.append(r)
    return out

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Parse Microsoft 365 Roadmap Markdown to CSV/JSON")
    ap.add_argument("--input", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--months", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="")
    ap.add_argument("--include", default="")
    ap.add_argument("--exclude", default="")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        md = f.read()

    headers, rows = parse_first_table(md)

    rows = filter_by_date(rows, headers, args.months, args.since, args.until)
    rows = filter_by_instance(rows, headers, args.include, args.exclude)

    # Final safety: ensure width alignment
    width = len(headers)
    normalized = []
    for r in rows:
        if len(r) < width:
            r = r + [""] * (width - len(r))
        elif len(r) > width:
            r = r[:width]
        normalized.append(r)

    # Write CSV
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(normalized)

    # Write JSON
    dicts = [dict(zip(headers, r)) for r in normalized]
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(dicts, f, ensure_ascii=False, indent=2)

    print(f"✅ Parsed {len(normalized)} rows into {args.csv} and {args.json}")

if __name__ == "__main__":
    main()
