#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Set

# Ensure "scripts" is importable whether run via module or file
try:
    from scripts.report_templates import FeatureRecord, normalize_clouds
except Exception:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.report_templates import FeatureRecord, normalize_clouds  # type: ignore


def read_rows(master_csv: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with master_csv.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def _row_id(r: Dict[str, str]) -> str:
    # Common ID aliases
    for k in (
        "PublicId",
        "MessageId",
        "id",
        "Id",
        "ID",
        "FeatureId",
        "Feature ID",
        "FeatureID",
        "Roadmap ID",
        "RoadmapId",
        "RoadmapID",
    ):
        v = r.get(k)
        if v and str(v).strip():
            return str(v).strip()
    # Fallback: any column containing "id"
    for k in r.keys():
        if "id" in k.lower():
            v = str(r.get(k, "")).strip()
            if v:
                return v
    return ""


def _row_updated_key(r: Dict[str, str]) -> Tuple[int, str]:
    s = (
        r.get("LastModified")
        or r.get("lastModifiedDateTime")
        or r.get("Last modified")
        or r.get("Last Modified")
        or r.get("updated")
        or r.get("Last Updated")
        or ""
    )
    return (1 if s else 0, s)


def dedupe_latest(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    latest: Dict[str, Dict[str, str]] = {}
    for r in rows:
        fid = _row_id(r)
        if not fid:
            continue
        if fid not in latest or _row_updated_key(r) > _row_updated_key(latest[fid]):
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


def _parse_date(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return dt.datetime.strptime(s[: len(fmt)], fmt)
        except Exception:
            pass
    return None


def main(argv: List[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Generate Markdown report from master CSV.")
    ap.add_argument("--title", required=True, help="Title for the report")
    ap.add_argument("--master", required=True, help="Path to master CSV")
    ap.add_argument("--out", required=True, help="Output Markdown path")
    ap.add_argument("--since", default="", help="ISO date filter (optional)")
    ap.add_argument("--months", default="", help="Lookback in months (optional)")
    ap.add_argument("--no-window", action="store_true", help="Compatibility flag (no-op)")

    # Accept CI flags and actually use them
    ap.add_argument(
        "--cloud",
        action="append",
        default=[],
        help='Repeatable cloud filter, e.g. "Worldwide (Standard Multi-Tenant)", "GCC", "GCC High", "DoD".',
    )
    ap.add_argument(
        "--forced-ids",
        default="",
        help="Comma/semicolon separated feature IDs to force-include (bypass date/cloud filters).",
    )

    args = ap.parse_args(argv)

    master = Path(args.master)
    if not master.exists():
        print(f"[generate_report] ERROR: master CSV missing: {master}", file=sys.stderr)
        write_report(args.title, [], Path(args.out))
        return 2

    rows = read_rows(master)
    total = len(rows)

    # Optional date window
    since_dt: dt.datetime | None = None
    if args.since.strip():
        since_dt = _parse_date(args.since.strip())
    elif args.months.strip():
        try:
            months = int(args.months.strip())
            since_dt = dt.datetime.utcnow() - dt.timedelta(days=months * 30)
        except Exception:
            since_dt = None

    def keep_row_by_date(r: Dict[str, str]) -> bool:
        if not since_dt:
            return True
        s = (
            r.get("LastModified")
            or r.get("lastModifiedDateTime")
            or r.get("Last modified")
            or r.get("Last Modified")
            or r.get("updated")
            or r.get("Last Updated")
            or ""
        )
        t = _parse_date(s)
        if not t:
            return True
        if t.tzinfo:
            t = t.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return t >= since_dt

    rows = [r for r in rows if _row_id(r)]
    with_id = len(rows)
    rows = [r for r in rows if keep_row_by_date(r)]
    after_date = len(rows)
    rows = dedupe_latest(rows)
    after_dedupe = len(rows)

    # Convert to records
    records = [FeatureRecord.from_row(r) for r in rows]

    # Cloud filter
    selected_clouds = normalize_clouds(",".join(args.cloud or []))
    if selected_clouds:
        sc = set(selected_clouds)
        records = [rec for rec in records if set(rec.clouds or []).intersection(sc)]

    # Forced IDs: ensure present
    forced_ids: Set[str] = set(
        s.strip() for s in (args.forced_ids or "").replace(";", ",").split(",") if s.strip()
    )
    if forced_ids:
        by_id = {rec.id: rec for rec in records}
        original = read_rows(master)
        for fid in forced_ids:
            for r in original:
                if _row_id(r) == fid:
                    by_id[fid] = FeatureRecord.from_row(r)
                    break
        records = list(by_id.values())

    write_report(args.title, records, Path(args.out))
    print(
        f"[generate_report] rows: total={total} with_id={with_id} after_date={after_date} after_dedupe={after_dedupe} final={len(records)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
