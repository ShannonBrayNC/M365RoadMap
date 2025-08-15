#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

H2_RE = re.compile(r"^##\s+\[(\d{3,8})\]\s+—\s+(.*)$")  # exact scaffold
FENCE_OPEN_RE = re.compile(r"^```feature\s*$")
FENCE_CLOSE_RE = re.compile(r"^```\s*$")

# Back-compat: tolerate older headings like "## Title — _Roadmap ID 123456_"
LEGACY_ID_IN_HEADING = re.compile(r"Roadmap ID[:\s]*([0-9]{3,8})", re.I)


def _parse_feature_meta(lines: List[str], start_idx: int) -> Tuple[Dict[str, str], int]:
    """
    If a ```feature meta block starts at start_idx, parse key/values (and simple lists).
    Returns (meta_dict, next_index_after_block). If no block, returns ({}, start_idx).
    """
    if start_idx >= len(lines) or not FENCE_OPEN_RE.match(lines[start_idx]):
        return {}, start_idx

    i = start_idx + 1
    meta: Dict[str, str] = {}
    key = None
    list_mode = False
    buf: List[str] = []
    lists: Dict[str, List[str]] = {}

    while i < len(lines):
        if FENCE_CLOSE_RE.match(lines[i]):
            # Flush any pending list
            if key and list_mode:
                lists.setdefault(key, []).extend(buf)
            break

        line = lines[i].rstrip("\n")
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*(.*)$", line):
            # New key
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
            key, val = m.group(1), m.group(2)
            if val == "[]":
                lists[key] = []
                list_mode = False
                buf = []
            elif val:
                meta[key] = val
                list_mode = False
                buf = []
            else:
                # Possibly list to follow
                list_mode = True
                buf = []
        elif list_mode and line.startswith("- "):
            buf.append(line[2:].strip())
        elif list_mode and line.startswith("  - "):
            buf.append(line[4:].strip())
        i += 1

    # Commit pending
    if key and list_mode and buf:
        lists.setdefault(key, []).extend(buf)

    # Merge lists into meta as comma-sep strings
    for k, vals in lists.items():
        meta[k] = ", ".join(vals)

    return meta, i + 1  # position after closing fence


def _maybe_extract_legacy_id(h2_text: str, chunk: List[str]) -> Optional[str]:
    m = LEGACY_ID_IN_HEADING.search(h2_text)
    if m:
        return m.group(1)
    joined = "\n".join(chunk)
    m = LEGACY_ID_IN_HEADING.search(joined)
    if m:
        return m.group(1)
    m = re.search(r"/feature/([0-9]{3,8})\b", joined)
    if m:
        return m.group(1)
    return None


def _within_date(last_modified: str, since_iso: Optional[str], months: Optional[int]) -> bool:
    if not last_modified:
        return True  # keep if unknown
    try:
        lm = dt.datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
    except Exception:
        return True
    if since_iso:
        try:
            since_dt = dt.datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
            if lm < since_dt:
                return False
        except Exception:
            pass
    if months is not None:
        # keep items within N months of now
        now = dt.datetime.now(dt.timezone.utc)
        delta = dt.timedelta(days=months * 30)
        if now - lm > delta:
            return False
    return True


def parse_document(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    records: List[Dict[str, str]] = []

    # Find all H2 anchors
    h2_positions: List[Tuple[int, re.Match]] = []
    for i, line in enumerate(lines):
        m = H2_RE.match(line)
        if m:
            h2_positions.append((i, m))

    # Back-compat: if none match strict scaffold, try to split on '## ' and infer IDs
    if not h2_positions:
        for i, line in enumerate(lines):
            if line.startswith("## "):
                fake = LEGACY_ID_IN_HEADING.search(line or "")
                if fake:
                    h2_positions.append((i, re.match(r"^##\s+\[(\d+)\]\s+—\s+(.*)$", f"## [{fake.group(1)}] — legacy",)))
        # Still none? Nothing to parse.
        if not h2_positions:
            return []

    # Walk sections
    for idx, m in h2_positions:
        rid = m.group(1)
        title = m.group(2).strip()

        # Section ends at next H2 or EOF
        next_idx = next((j for j, _ in h2_positions if j > idx), len(lines))
        chunk = lines[idx:next_idx]

        # Meta block
        meta, after = _parse_feature_meta(lines, idx + 2)  # usually an empty line after H2
        if not meta.get("id"):
            # Legacy fallback
            legacy = _maybe_extract_legacy_id(lines[idx], chunk)
            if legacy:
                meta["id"] = legacy

        rec = {
            "id": meta.get("id", rid),
            "title": meta.get("title", title),
            "cloud": meta.get("cloud", ""),
            "status": meta.get("status", ""),
            "last_modified": meta.get("last_modified", ""),
            "sources": meta.get("sources", ""),
            "tags": meta.get("tags", ""),
        }
        records.append(rec)

    return records


def write_outputs(recs: List[Dict[str, str]], csv_out: Optional[Path], json_out: Optional[Path]) -> None:
    if csv_out:
        if not recs:
            print("No data to write to CSV.")
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        with csv_out.open("w", encoding="utf-8", newline="") as f:
            cols = ["id", "title", "cloud", "status", "last_modified", "sources", "tags"]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in recs:
                w.writerow({k: r.get(k, "") for k in cols})
        print(f"CSV written to {csv_out}")
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON written to {json_out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse strict-scaffold Roadmap Markdown into CSV/JSON")
    ap.add_argument("--input", required=True)
    ap.add_argument("--csv", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--months", type=int, default=None, help="only include items within N months of now")
    ap.add_argument("--since", default="", help="ISO date lower bound (YYYY-MM-DD)")
    args = ap.parse_args()

    text = Path(args.input).read_text(encoding="utf-8")
    recs = parse_document(text)

    # Date filtering (optional)
    months = args.months
    since_iso = args.since.strip() or None
    filtered = [
        r for r in recs if _within_date(r.get("last_modified", ""), since_iso=since_iso, months=months)
    ]

    csv_out = Path(args.csv) if args.csv else None
    json_out = Path(args.json) if args.json else None
    write_outputs(filtered, csv_out, json_out)


if __name__ == "__main__":
    main()
