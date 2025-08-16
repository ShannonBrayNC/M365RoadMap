#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Be liberal with import path — works when running as a module or script
try:
    from report_templates import (  # type: ignore
        FeatureRecord,
        normalize_clouds,
        render_feature_markdown,
        render_header,
        render_toc,
    )
except Exception:  # pragma: no cover
    from scripts.report_templates import (  # type: ignore[no-redef]
        FeatureRecord,
        normalize_clouds,
        render_feature_markdown,
        render_header,
        render_toc,
    )

# --- CSV columns we expect from fetch_messages_graph.py ---
CSV_COLS = [
    "PublicId",
    "Title",
    "Source",
    "Product_Workload",
    "Status",
    "LastModified",
    "ReleaseDate",
    "Cloud_instance",
    "Official_Roadmap_link",
    "MessageId",
]

# --- utils ---


def _split_csv_like(s: str) -> list[str]:
    if not s:
        return []
    parts = re.split(r"[,\|\n\r\t]+", s)
    return [p.strip() for p in parts if p.strip()]


def parse_date_soft(s: str) -> Optional[dt.date]:
    """
    Best-effort parse 'YYYY-MM-DD' or ISO date/time. Returns date or None.
    """
    if not s:
        return None
    s = s.strip()
    # quick YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    # ISO-ish
    s2 = s.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s2).date()
    except Exception:
        return None


def _cloud_display_from_args(clouds: list[str]) -> str:
    if not clouds:
        return "General"
    normalized = normalize_clouds(clouds)
    return ", ".join(sorted(normalized)) if normalized else "General"


# --- reading & mapping ---


def _read_master_csv(path: str | Path) -> list[FeatureRecord]:
    p = Path(path)
    rows: list[FeatureRecord] = []
    if not p.exists():
        return rows
    with p.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for d in r:
            # Defensive get with defaults
            rows.append(
                FeatureRecord(
                    public_id=(d.get("PublicId") or "").strip(),
                    title=(d.get("Title") or "").strip(),
                    source=(d.get("Source") or "").strip(),
                    product_workload=(d.get("Product_Workload") or "").strip(),
                    status=(d.get("Status") or "").strip(),
                    last_modified=(d.get("LastModified") or "").strip(),
                    release_date=(d.get("ReleaseDate") or "").strip(),
                    cloud_instance=(d.get("Cloud_instance") or "").strip(),
                    official_roadmap_link=(d.get("Official_Roadmap_link") or "").strip(),
                    message_id=(d.get("MessageId") or "").strip(),
                )
            )
    return rows


# --- filtering ---


def _filter_by_date(rows: list[FeatureRecord], since: Optional[str], months: Optional[int]) -> list[FeatureRecord]:
    if not since and not months:
        return rows[:]

    since_date: Optional[dt.date] = parse_date_soft(since) if since else None
    if not since_date and months:
        since_date = dt.date.today() - dt.timedelta(days=30 * months)

    if not since_date:
        return rows[:]

    out: list[FeatureRecord] = []
    for r in rows:
        # Prefer LastModified; fall back to ReleaseDate
        d = parse_date_soft(r.last_modified) or parse_date_soft(r.release_date)
        if not d or d < since_date:
            continue
        out.append(r)
    return out


def _include_by_cloud(cloud_field: str, selected: set[str]) -> bool:
    if not selected:
        return True
    raw = (cloud_field or "").strip()
    canon = normalize_clouds([raw]) if raw else {"General"}
    return bool(canon & selected)


def _filter_by_cloud(rows: list[FeatureRecord], clouds: Iterable[str]) -> list[FeatureRecord]:
    selected = normalize_clouds(list(clouds)) if clouds else set()
    if not selected:
        selected = {"General"}
    return [r for r in rows if _include_by_cloud(r.cloud_instance, selected)]


def _filter_by_products(rows: list[FeatureRecord], products_filter: str) -> list[FeatureRecord]:
    """
    products_filter: comma/pipe separated keywords. Any match (case-insensitive) in product_workload keeps the row.
    Blank → no filtering.
    """
    terms = [t.lower() for t in _split_csv_like(products_filter)]
    if not terms:
        return rows[:]
    out: list[FeatureRecord] = []
    for r in rows:
        hay = (r.product_workload or "").lower()
        if any(t in hay for t in terms):
            out.append(r)
    return out


# --- forced ids: synthesize and ordering ---


def _synthesize_forced(public_id: str) -> FeatureRecord:
    link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}"
    return FeatureRecord(
        public_id=public_id,
        title=f"[{public_id}]",
        source="seed",
        product_workload="",
        status="",
        last_modified="",
        release_date="",
        cloud_instance="",  # treated as General in filters
        official_roadmap_link=link,
        message_id="",
    )


def _apply_forced_ids(rows: list[FeatureRecord], forced_ids_csv: str) -> list[FeatureRecord]:
    """
    Ensure all forced IDs are present, and order the final list with those IDs first in the given order.
    Remaining features follow in their original order.
    """
    if not forced_ids_csv:
        return rows[:]
    forced = [x for x in _split_csv_like(forced_ids_csv) if x]
    if not forced:
        return rows[:]

    # Index existing by id
    by_id = {r.public_id: r for r in rows if r.public_id}
    out: list[FeatureRecord] = []

    # Add all forced (synthesizing when missing)
    seen: set[str] = set()
    for pid in forced:
        r = by_id.get(pid) or _synthesize_forced(pid)
        out.append(r)
        seen.add(r.public_id)

    # Append the rest preserving original order
    for r in rows:
        if r.public_id and r.public_id in seen:
            continue
        out.append(r)

    return out


# --- writing ---

def _write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --- CLI ---

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="CSV file from fetch_messages_graph")
    p.add_argument("--out", required=True, help="Output markdown path")
    p.add_argument("--since", default="")
    p.add_argument("--months", default="")
    p.add_argument("--cloud", action="append", default=[], help="Repeatable; if omitted, defaults to General")
    p.add_argument("--products", default="", help="Comma/pipe-separated filter. Blank = all.")
    p.add_argument("--forced-ids", default="", help="Comma-separated PublicId list to force/include (ordered).")
    return p.parse_args()


# --- MAIN ---

def main() -> None:
    args = parse_args()

    # Load
    all_rows = _read_master_csv(args.master)

    # Time filter
    rows = _filter_by_date(all_rows, since=args.since or None, months=int(args.months) if (args.months or "").isdigit() else None)

    # Cloud filter
    rows = _filter_by_cloud(rows, args.cloud)

    # Product filter
    rows = _filter_by_products(rows, args.products)

    # Forced IDs (synthesize + put first in provided order)
    rows = _apply_forced_ids(rows, args.forced_ids)

    # Build header & sections
    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = _cloud_display_from_args(args.cloud)
    header = render_header(title=args.title, generated_utc=generated, cloud_display=cloud_display)

    count_line = f"**Total features:** {len(rows)}\n\n"
    toc = render_toc(rows)

    parts = [header, count_line, toc]

    # Feature sections
    for r in rows:
        parts.append(render_feature_markdown(r))

    # Write
    _write_text(args.out, "".join(parts))


if __name__ == "__main__":
    main()
