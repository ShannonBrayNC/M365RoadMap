#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import Iterable, Optional

from report_templates import (
    FeatureRecord,
    render_header,
    render_table_of_contents,
    render_feature_markdown,
)


# ---------- Cloud normalization / filtering ----------


def _normalize_cloud_label(label: str) -> str:
    lab = label.strip().lower()
    if "dod" in lab:
        return "DoD"
    if "high" in lab:
        return "GCC High"
    if "gcc" in lab:
        return "GCC"
    if "worldwide" in lab or "general" in lab or "multi-tenant" in lab:
        return "General"
    return label.strip() or "General"


def _filter_by_cloud(rows: list[FeatureRecord], clouds: list[str]) -> list[FeatureRecord]:
    selected = {_normalize_cloud_label(c) for c in (clouds or []) if c}
    if not selected:
        return rows
    out: list[FeatureRecord] = []
    for r in rows:
        c = _normalize_cloud_label(r.cloud_instance or "")
        if c in selected:
            out.append(r)
    return out


def _split_csv_like(s: str | None) -> list[str]:
    if not s:
        return []
    import re

    parts = [p for p in re.split(r"[,\|\s]+", s.strip()) if p]
    return parts


def _filter_by_products(rows: list[FeatureRecord], products: str) -> list[FeatureRecord]:
    if not products:
        return rows
    wants = {p.lower() for p in _split_csv_like(products)}
    if not wants:
        return rows
    out: list[FeatureRecord] = []
    for r in rows:
        hay = (r.product_workload or "").lower()
        if any(w in hay for w in wants):
            out.append(r)
    return out


# ---------- IO ----------


def _read_master_csv(path: str | Path) -> list[FeatureRecord]:
    rows: list[FeatureRecord] = []
    p = Path(path)
    if not p.exists():
        return rows
    with p.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for raw in r:
            rows.append(FeatureRecord.from_csv_row(raw))
    return rows


# ---------- MAIN ----------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--since", default="")
    p.add_argument("--months", default="")
    p.add_argument("--cloud", action="append", default=[])
    p.add_argument("--products", default="")
    p.add_argument("--forced-ids", default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    all_rows = _read_master_csv(args.master)
    print(f"[gen] read={len(all_rows)} from {args.master}")

    # Cloud filter label for header
    cloud_display = ", ".join({_normalize_cloud_label(c) for c in args.cloud}) or "General"

    rows = _filter_by_cloud(all_rows, args.cloud)
    print(f"[gen] after cloud filter ({[cloud_display]}): {len(rows)}")

    rows = _filter_by_products(rows, args.products)

    # Forced IDs ordering (and injection if master doesn't have them)
    forced_ids = _split_csv_like(args.forced_ids)
    if forced_ids:
        by_id = {r.public_id: r for r in rows}
        ordered: list[FeatureRecord] = []
        for fid in forced_ids:
            if fid in by_id:
                ordered.append(by_id[fid])
            else:
                # synthesize a minimal row
                ordered.append(
                    FeatureRecord(
                        public_id=fid,
                        title=f"[{fid}]",
                        source="forced",
                        product_workload="",
                        status="",
                        last_modified="",
                        release_date="",
                        cloud_instance="",
                        official_roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={fid}",
                        message_id="",
                    )
                )
        # Add any remaining rows not explicitly forced
        seen = {r.public_id for r in ordered}
        for r in rows:
            if r.public_id not in seen:
                ordered.append(r)
        rows = ordered

    print(f"[gen] final row count: {len(rows)}")

    # Render
    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    parts: list[str] = [
        render_header(title=args.title, generated_utc=generated, cloud_display=cloud_display)
    ]

    # Table of contents (mini)
    parts.append(render_table_of_contents(rows))

    # Feature sections
    for rec in rows:
        parts.append(render_feature_markdown(rec))

    out = "\n".join(parts).rstrip() + "\n"

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out, encoding="utf-8")
    print(f"Wrote report: {out_path} (features={len(rows)})")


if __name__ == "__main__":
    main()
