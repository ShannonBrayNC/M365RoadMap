#!/usr/bin/env python3
"""
validate_report.py — sanity checks for the generated Markdown report

Validates:
- Exactly one "Master Summary Table (all IDs)" section exists
- Exactly one GFM pipe table follows that heading
- Table header matches EXACTLY (text + order)
- Separator row has pipes/dashes (|---|)
- No other tables appear anywhere else
- (Optional) Each ID in the master table has a Deep Dive section

Exit codes:
 0 = OK
 1 = validation failed

Usage:
  python scripts/validate_report.py --input output/<title>.md [--check-deep-dive]
"""

import argparse
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


MASTER_H = re.compile(r"^##\s*Master Summary Table\s*\(all IDs\)\s*$", re.IGNORECASE)
SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
TABLE_HEADER_EXPECTED = [
    "ID",
    "Title",
    "Product/Workload",
    "Status",
    "Release phase",
    "Targeted dates",
    "Cloud instance",
    "Short description",
    "Official Roadmap link",
]


def split_row(s: str):
    s = s.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    parts = [c.strip() for c in s.split("|")]
    # trim trailing empty cells
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def find_master_table(lines):
    """
    Return (header_line_idx, sep_line_idx, first_row_idx, last_row_idx)
    for the single table after the Master heading. Returns None if not found.
    """
    # Find the Master section heading
    hidx = None
    for i, ln in enumerate(lines):
        if MASTER_H.match(ln.strip()):
            hidx = i
            break
    if hidx is None:
        return None

    # Find first table after this heading
    # scan forward until a header line with '|' and a sep line follows
    for i in range(hidx + 1, len(lines) - 1):
        line = lines[i].rstrip("\n")
        nxt = lines[i + 1].rstrip("\n")
        if "|" in line and SEP_RE.match(nxt):
            # We found a table start; now collect rows until non-pipe or blank section break
            first_row = i + 2
            j = first_row
            while j < len(lines):
                ln = lines[j].rstrip("\n")
                if ln.strip().startswith("|"):
                    if SEP_RE.match(ln):  # tolerate accidental extra sep lines
                        j += 1
                        continue
                    j += 1
                    continue
                # stop at next non-table line (blank is allowed to end table)
                break
            last_row = j - 1
            return (i, i + 1, first_row, last_row)
    return None


def find_all_tables(lines):
    """Return a list of (header_idx, sep_idx, first_row_idx, last_row_idx) for all pipe tables in the doc."""
    out = []
    i = 0
    while i < len(lines) - 1:
        line = lines[i].rstrip("\n")
        nxt = lines[i + 1].rstrip("\n")
        if "|" in line and SEP_RE.match(nxt):
            first_row = i + 2
            j = first_row
            while j < len(lines):
                ln = lines[j].rstrip("\n")
                if ln.strip().startswith("|"):
                    if SEP_RE.match(ln):
                        j += 1
                        continue
                    j += 1
                    continue
                break
            out.append((i, i + 1, first_row, j - 1))
            i = j
        else:
            i += 1
    return out


def parse_ids_from_table(lines, header_idx, sep_idx, first_row_idx, last_row_idx):
    header_cells = split_row(lines[header_idx])
    # Hard check: exact match
    if header_cells != TABLE_HEADER_EXPECTED:
        return (
            None,
            f"Header mismatch.\nExpected: {TABLE_HEADER_EXPECTED}\nFound:    {header_cells}",
        )

    ids = []
    for i in range(first_row_idx, last_row_idx + 1):
        row = split_row(lines[i])
        if not row:
            continue
        # Be tolerant of short rows (fill)
        if len(row) < len(header_cells):
            row = row + [""] * (len(header_cells) - len(row))
        ids.append(row[0])
    return ids, None


def deep_dive_sections_present(lines, ids):
    """
    For each ID, check there is a '### <ID>:' or '### <ID>' heading somewhere after the table.
    Return list of missing IDs.
    """
    doc = "\n".join(lines)
    missing = []
    for rid in ids:
        if not rid.strip():
            continue
        # Accept "### <ID>:" or "### <ID> - " or "### <ID> " somewhere
        pattern = rf"^###\s*{re.escape(rid)}\b"
        if not re.search(pattern, doc, re.MULTILINE):
            missing.append(rid)
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--check-deep-dive", action="store_true")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        lines = f.read().splitlines()

    errors = []

    # Exactly one Master table
    master = find_master_table(lines)
    if not master:
        errors.append(
            "Could not find '## Master Summary Table (all IDs)' followed by a GFM pipe table."
        )
    else:
        header_idx, sep_idx, first_row_idx, last_row_idx = master
        # Validate separator visually (already matched by regex)
        if not SEP_RE.match(lines[sep_idx]):
            errors.append("Separator row under Master table header is not a valid '|---|' row.")

        # Validate header EXACT match and collect IDs
        ids, err = parse_ids_from_table(lines, header_idx, sep_idx, first_row_idx, last_row_idx)
        if err:
            errors.append(err)

        # Ensure there is exactly one table total in the document
        all_tables = find_all_tables(lines)
        if len(all_tables) != 1:
            errors.append(f"Expected exactly 1 table in the document, found {len(all_tables)}.")

        # Deep Dive sections per ID
        if not errors and args.check_deep_dive and ids:
            missing = deep_dive_sections_present(lines, ids)
            if missing:
                errors.append(f"Deep Dive sections missing for IDs: {', '.join(missing)}")

    if errors:
        print("❌ Report validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("✅ Report validation passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
