#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Make "scripts" importable even when running as a file
try:
    from scripts.report_templates import FeatureRecord
except Exception:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.report_templates import FeatureRecord  # type: ignore


def read_rows(master_csv: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with master_csv.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def dedupe_latest(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Keep the latest row per id using lastModifiedDateTime (or preserve order).
    """
    def get_id(r: Dict[str, str]) -> str:
        for k in ("id", "Id", "ID", "FeatureId", "Feature ID"):
            v = r.get(k)
            if v:
                return str(v).strip()
        return ""

    def get_updated(r: Dict[str, str]) -> Tuple[int, str]:
        # Fallback to '' so max keeps later string order if needed
        s = r.get("lastModifiedDateTime") or r.get("Last modified") or r.get("updated") or ""
        return (0, s)

    latest: Dict[str, Dict[str, str]] = {}
    for r in rows:
        fid = get_id(r)
        if not fid:
            # keep non-id rows out
            continue
        if fid not in latest:
            latest[fid] = r
            continue
        # naive compare; if equal we keep first
        if get_updated(r) > get_updated(latest[fid]):
            latest[fid] = r
    return list(latest.values())


def write_report(title: str, records: List[FeatureRecord], out_md: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    with out_md.open("w", encoding="utf-8", newline="\n") as w:
        w.write(f"# {title}\n\n")
        w.write(f"_Generated {now}_\n\n")
        w.write("---\n\n")
        for rec in records:
            w.write(rec.render_markdown())
    print(f"Wrote report: {out_md} (features={len(records)})", file=sys.stderr)


def main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Generate Markdown report from master CSV.")
    ap.add_argument("--title", required=True, help="Title for the report")
    ap.add_argument("--master", required=True, help="Path to master CSV")
    ap.add_argument("--out", required=True, help="Output Markdown path")
    ap.add_argument("--since", default="", help="ISO date filter (optional)")
    ap.add_argument("--months", default="", help="Lookback in months (optional)")
    ap.add_argument("--no-window", action="store_true", help="(compat flag) ignored")
    args = ap.parse_args(argv)

    master = Path(args.master)
    if not master.exists():
        print(f"[generate_report] ERROR: master CSV missing: {master}", file=sys.stderr)
        # still write header so downstream won't crash
        write_report(args.title, [], Path(args.out))
        return 2

    rows = read_rows(master)
    if not rows:
        write_report(args.title, [], Path(args.out))
        return 0

    # Optional date filter
    since_dt: dt.datetime | None = None
    if args.since.strip():
        try:
            since_dt = dt.datetime.fromisoformat(args.since.strip())
        except Exception:
            pass
    elif args.months.strip():
        try:
            months = int(args.months.strip())
            since_dt = dt.datetime.utcnow() - dt.timedelta(days=months * 30)
        except Exception:
            pass

    def keep_row(r: Dict[str, str]) -> bool:
        if not since_dt:
            return True
        s = r.get("lastModifiedDateTime") or r.get("Last modified") or r.get("updated")
        if not s:
            return True
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                # best effort
                t = dt.datetime.strptime(s[: len(fmt)], fmt)
                break
            except Exception:
                t = None  # type: ignore
        if not t:
            return True
        if t.tzinfo:
            t = t.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return t >= since_dt

    rows = [r for r in rows if keep_row(r)]
    rows = dedupe_latest(rows)
    records = [FeatureRecord.from_row(r) for r in rows if r]
    write_report(args.title, records, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
