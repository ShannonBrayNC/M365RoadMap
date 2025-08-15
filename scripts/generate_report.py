#!/usr/bin/env python3
from __future__ import annotations

# Allows `python scripts/generate_report.py` from repo root
try:
    from scripts import _importlib_local  # noqa: F401
except Exception:
    pass

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from scripts.report_templates import (
    CLOUD_LABELS,
    FeatureRecord,
    normalize_clouds,
    parse_date_soft,
)


def months_to_dt_utc_approx(months: int) -> dt.datetime:
    days = max(1, int(months) * 30)  # rough but fine for filtering
    return dt.datetime.utcnow() - dt.timedelta(days=days)


def want_cloud(row_tags: Set[str], selected: Set[str]) -> bool:
    if not selected:
        return True
    if row_tags:
        return bool(row_tags & selected)
    # Treat missing cloud as "General" if General was explicitly requested
    return "General" in selected


def read_master(master_csv: Path) -> List[Dict[str, str]]:
    with master_csv.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        return list(rdr)


def dedupe_latest(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Keep the last occurrence per PublicId (assumes input already roughly sorted)
    seen: Dict[str, Dict[str, str]] = {}
    for r in rows:
        key = (r.get("PublicId") or r.get("Public_ID") or "").strip()
        if key:
            seen[key] = r
    return list(seen.values())


def sort_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def key(r: Dict[str, str]):
        dm = parse_date_soft((r.get("LastModified") or r.get("Last_Modified") or "").strip()) or dt.datetime.min
        return (dm, (r.get("PublicId") or ""))
    return sorted(rows, key=key, reverse=True)


def build_feature_records(rows: Iterable[Dict[str, str]]) -> List[FeatureRecord]:
    return [FeatureRecord.from_row(r) for r in rows]


def compute_cloud_hist(rows: Iterable[FeatureRecord]) -> Dict[str, int]:
    hist = {k: 0 for k in CLOUD_LABELS}
    for r in rows:
        if not r.clouds:
            continue
        for c in r.clouds:
            if c in hist:
                hist[c] += 1
    return hist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="Report title")
    ap.add_argument("--master", required=True, help="Path to master CSV")
    ap.add_argument("--out", required=True, help="Output Markdown path")
    ap.add_argument("--since", default="", help="YYYY-MM-DD; filter LastModified >= since")
    ap.add_argument("--months", type=int, default=None, help="Lookback months (approx)")
    ap.add_argument(
        "--cloud",
        action="append",
        default=None,
        help="Cloud(s) to include. Accepts values like 'General', 'GCC', 'GCC High', 'DoD', "
             "or long phrases like 'Worldwide (Standard Multi-Tenant)'. May be given multiple times.",
    )
    ap.add_argument("--no-window", action="store_true", help="(No-op in generator; kept for CLI parity)")

    args = ap.parse_args()

    title = args.title
    master_csv = Path(args.master)
    out_md = Path(args.out)

    since_dt: Optional[dt.datetime] = None
    if args.months is not None:
        since_dt = months_to_dt_utc_approx(args.months)
    if args.since:
        try:
            since_dt = dt.datetime.strptime(args.since.strip(), "%Y-%m-%d")
        except Exception:
            pass

    # Selected clouds
    selected: Set[str] = set()
    if args.cloud:
        for v in args.cloud:
            selected |= normalize_clouds(v)
    # If user passed the long phrase, normalize to General at minimum
    # (normalize_clouds already handles it)
    # selected now is canonical labels only

    rows = read_master(master_csv)
    total = len(rows)

    if since_dt is not None:
        rows = [
            r
            for r in rows
            if (parse_date_soft((r.get("LastModified") or r.get("Last_Modified") or "").strip()) or dt.datetime.min)
            >= since_dt
        ]
    after_date = len(rows)

    rows = dedupe_latest(rows)
    after_dedupe = len(rows)

    # Convert to FeatureRecord so we can compute clouds cleanly
    feats = build_feature_records(rows)

    # Cloud filter
    feats_filtered = [fr for fr in feats if want_cloud(fr.clouds, selected)]
    final_count = len(feats_filtered)

    # Stats for quick visibility
    hist = compute_cloud_hist(feats)
    print(
        f"[generate_report] rows: total={total} after_date={after_date} after_dedupe={after_dedupe} "
        f"final={final_count} | cloud_hist={hist} | selected={sorted(selected) if selected else 'ALL'}"
    )

    # Write Markdown ---------------------------------------------------
    lines: List[str] = []
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"_Generated {now}_")
    if selected:
        lines.append(f"_Cloud filter: {', '.join(sorted(selected))}_")
    if since_dt:
        lines.append(f"_Since: {since_dt.date().isoformat()}_")
    lines.append("")
    lines.append(f"Total features: **{final_count}**")
    lines.append("")

    for fr in feats_filtered:
        lines.append(fr.render_markdown())

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote report: {out_md} (features={final_count})")


if __name__ == "__main__":
    main()
