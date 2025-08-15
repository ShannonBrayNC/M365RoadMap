#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


META_RE = re.compile(r"<!--\s*META\s+(\{.*?\})\s*-->", re.IGNORECASE | re.DOTALL)
BLOCK_RE = re.compile(
    r"<!--\s*FEATURE:(\d+):START\s*-->(.*?)<!--\s*FEATURE:\1:END\s*-->",
    re.IGNORECASE | re.DOTALL,
)


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _parse_blocks(md: str) -> Iterable[Tuple[str, Dict]]:
    for m in BLOCK_RE.finditer(md):
        fid = m.group(1)
        block = m.group(2)
        meta_m = META_RE.search(block)
        if not meta_m:
            continue
        try:
            meta = json.loads(meta_m.group(1))
        except Exception:
            continue
        # ensure id consistency
        meta.setdefault("id", fid)
        yield fid, meta


def _parse_iso(d: str | None) -> dt.datetime | None:
    if not d:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ):
        try:
            return dt.datetime.strptime(d[: len(fmt)], fmt)
        except Exception:
            pass
    return None


def _filter_by_date(items: List[Dict], since: str, months: str) -> List[Dict]:
    since_dt: dt.datetime | None = None
    if since.strip():
        try:
            since_dt = dt.datetime.fromisoformat(since.strip())
        except Exception:
            since_dt = None
    elif months.strip():
        try:
            since_dt = dt.datetime.utcnow() - dt.timedelta(days=int(months) * 30)
        except Exception:
            since_dt = None
    if not since_dt:
        return items
    out = []
    for it in items:
        t = _parse_iso(it.get("updated"))
        if not t:
            out.append(it)
            continue
        if t.tzinfo:
            t = t.astimezone(dt.timezone.utc).replace(tzinfo=None)
        if t >= since_dt:
            out.append(it)
    return out


def write_csv(items: List[Dict], out_csv: Path) -> None:
    if not items:
        # still create empty file with header to avoid downstream failures
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "product", "status", "release_phase", "eta", "clouds", "updated", "link", "source"])
        print("No data to write to CSV.")
        print(f"CSV written to {out_csv}")
        return
    keys = ["id", "title", "product", "status", "release_phase", "eta", "clouds", "updated", "link", "source"]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for it in items:
            it = {**{k: "" for k in keys}, **it}
            if isinstance(it.get("clouds"), list):
                it["clouds"] = ", ".join(it["clouds"])
            w.writerow({k: it.get(k, "") for k in keys})
    print(f"CSV written to {out_csv}")


def write_json(items: List[Dict], out_json: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON written to {out_json}")


def main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Parse feature blocks from Markdown produced by generate_report.py")
    ap.add_argument("--input", required=True, help="Input Markdown path")
    ap.add_argument("--csv", default="", help="Output CSV path (optional)")
    ap.add_argument("--json", default="", help="Output JSON path (optional)")
    ap.add_argument("--since", default="", help="ISO date (optional)")
    ap.add_argument("--months", default="", help="Lookback months (optional)")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        print(f"[parse_roadmap_markdown] ERROR: missing {src}", file=sys.stderr)
        return 2

    text = _read_text(src)
    items = [meta for _, meta in _parse_blocks(text)]

    # Date filter (for robustness we treat empty strings as unset)
    items = _filter_by_date(items, args.since or "", args.months or "")

    if args.csv:
        write_csv(items, Path(args.csv))
    if args.json:
        write_json(items, Path(args.json))

    # Quiet success if neither csv/json requested
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
