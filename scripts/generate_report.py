#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from typing import Iterable, List, Mapping, Optional, Sequence

# Date parsing (soft)
try:
    from dateutil import parser as dateparser
    from dateutil.relativedelta import relativedelta
except Exception:  # pragma: no cover
    dateparser = None
    relativedelta = None

# Import templates robustly (works from repo root or inside scripts/)
try:
    from scripts.report_templates import (
        FeatureRecord,
        render_header,
        render_feature_markdown,
        render_toc,
        normalize_clouds,
        cloud_display_from,
    )
except Exception:
    from report_templates import (  # type: ignore
        FeatureRecord,
        render_header,
        render_feature_markdown,
        render_toc,
        normalize_clouds,
        cloud_display_from,
    )


# ---------- helpers ----------

def _split_csv_like(s: str | None) -> list[str]:
    if not s:
        return []
    raw = s.replace(";", ",").replace("|", ",").replace("/", ",")
    out: list[str] = []
    seen: set[str] = set()
    for p in (piece.strip() for piece in raw.split(",") if piece.strip()):
        if p.lower() not in seen:
            out.append(p)
            seen.add(p.lower())
    return out


def _read_master_csv(path: str) -> list[FeatureRecord]:
    rows: list[FeatureRecord] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            rows.append(FeatureRecord.from_csv_row(row))
    return rows


def _parse_date_soft(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    if dateparser is None:
        return None
    try:
        dt = dateparser.parse(s)
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _filter_by_date(
    rows: Sequence[FeatureRecord],
    since: Optional[str],
    months: Optional[int],
) -> list[FeatureRecord]:
    if not since and not months:
        return list(rows)

    since_dt: Optional[datetime] = _parse_date_soft(since) if since else None
    cutoff_dt: Optional[datetime] = None
    if months and relativedelta is not None:
        cutoff_dt = datetime.now(tz=timezone.utc) - relativedelta(months=int(months))

    def keep(r: FeatureRecord) -> bool:
        lm = _parse_date_soft(r.last_modified)
        rd = _parse_date_soft(r.release_date)
        cands = [d for d in (lm, rd) if d is not None]
        if not cands:
            return True  # keep undated rows
        if since_dt and any(d >= since_dt for d in cands):
            return True
        if cutoff_dt and any(d >= cutoff_dt for d in cands):
            return True
        # If both filters present, keep if either passes:
        if (since_dt or cutoff_dt) and not since_dt and not cutoff_dt:
            return False
        return bool(since_dt or cutoff_dt)

    return [r for r in rows if keep(r)]


def _filter_by_cloud(
    rows: Sequence[FeatureRecord],
    selected_clouds: Optional[Sequence[str]],
) -> list[FeatureRecord]:
    if not selected_clouds:
        return list(rows)
    wanted = normalize_clouds(selected_clouds)
    if not wanted:
        return list(rows)

    out: list[FeatureRecord] = []
    for r in rows:
        row_clouds = set(normalize_clouds(r.clouds))
        if not row_clouds:
            # If row has no clouds labeled, include by default
            out.append(r)
            continue
        if row_clouds & wanted:
            out.append(r)
    return out


def _filter_by_products(
    rows: Sequence[FeatureRecord],
    products: Optional[str],
) -> list[FeatureRecord]:
    tokens = [t.lower() for t in _split_csv_like(products)]
    if not tokens:
        return list(rows)
    out: list[FeatureRecord] = []
    for r in rows:
        hay = (r.product or "").lower()
        if any(t in hay for t in tokens):
            out.append(r)
    return out


def _synth_placeholder(public_id: str) -> FeatureRecord:
    rid = public_id.strip()
    return FeatureRecord(
        public_id=rid,
        title=f"[{rid}]",
        product="",
        status="",
        clouds=[],
        last_modified="",
        release_date="",
        source="forced",
        message_id="",
        roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}",
    )


def _apply_forced_ids(rows: Sequence[FeatureRecord], forced_ids: Optional[str]) -> list[FeatureRecord]:
    if not forced_ids:
        return list(rows)
    order = [i.strip() for i in _split_csv_like(forced_ids) if i.strip()]
    if not order:
        return list(rows)

    by_id = {r.public_id: r for r in rows}
    used: set[str] = set()
    out: list[FeatureRecord] = []

    # exact ordering for forced IDs (synthesizing if missing)
    for rid in order:
        out.append(by_id.get(rid) or _synth_placeholder(rid))
        used.add(rid)

    # then append the rest
    out.extend(r for rid, r in by_id.items() if rid not in used)
    return out


# ---------- main ----------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate roadmap markdown from master CSV.")
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="Path to *_master.csv produced by fetch step")
    p.add_argument("--out", required=True, help="Output markdown path")
    p.add_argument("--since", default=None, help="Only include items on/after YYYY-MM-DD")
    p.add_argument("--months", type=int, default=None, help="Only include items in last N months")
    p.add_argument("--cloud", action="append", default=None, help="Repeatable; e.g. 'Worldwide (Standard Multi-Tenant)' or 'GCC'")
    p.add_argument("--products", default="", help="Comma/pipe separated list; blank = all")
    p.add_argument("--forced-ids", default="", help="Comma-separated PublicId list to force/include (ordered)")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)

    # Read master CSV
    all_rows = _read_master_csv(args.master)

    # Time filters
    time_rows = _filter_by_date(all_rows, args.since, args.months)

    # Cloud filters
    cloud_rows = _filter_by_cloud(time_rows, args.cloud)

    # Product filters
    prod_rows = _filter_by_products(cloud_rows, args.products)

    # Forced IDs (exact ordering + synthesize missing)
    rows = _apply_forced_ids(prod_rows, args.forced_ids)

    # Header meta
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = cloud_display_from(args.cloud or []) if args.cloud else "All"

    # Compose document
    parts: list[str] = []
    parts.append(
        render_header(
            title=args.title,
            generated_utc=generated,
            cloud_display=cloud_display,
        )
    )

    parts.append(f'<div class="rm-wrap"><div class="rm-meta">Total features: <strong>{len(rows)}</strong></div></div>')

    # TOC
    parts.append(render_toc(rows))

    # Cards
    for rec in rows:
        ai_sections = {
            # Placeholders; your AI pipeline can overwrite these.
            "summary": "",
            "changes": "",
            "impact": "",
            "actions": "",
        }
        parts.append(render_feature_markdown(rec, ai_sections=ai_sections))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


if __name__ == "__main__":
    main()
