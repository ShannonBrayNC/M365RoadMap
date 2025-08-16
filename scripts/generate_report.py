#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

# ---------- try to import UI helpers; fallback to internal pretties ----------

try:
    # Local import (same folder)
    from report_templates import (  # type: ignore
        render_header,
        render_feature_markdown,
    )
except Exception:
    # Fallback renderers so the script still works if report_templates isn't importable.
    def _md_link(text: str, url: str) -> str:
        if not url:
            return text
        return f"[{text}]({url})"

    def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
        return (
            f"# {title}\n"
            f"_Generated {generated_utc}_\n\n"
            f"**Cloud filter:** {cloud_display}\n\n"
        )

    def render_feature_markdown(
        *,
        public_id: str,
        title: str,
        product: str,
        status: str,
        clouds: str,
        last_modified: str,
        release_date: str,
        source: str,
        message_id: str,
        roadmap_link: str,
        summary: str | None = None,
        details: str | None = None,
        impact: str | None = None,
        actions: str | None = None,
    ) -> str:
        # “Products pills”
        pills = ""
        if product:
            parts = [p.strip() for p in re.split(r"[,/|]+", product) if p.strip()]
            if parts:
                pills = " ".join([f"`{p}`" for p in parts])
        # Strong title w/ roadmap link next to it
        title_line = f"**{title}**"
        if public_id:
            title_line += f"  \n{_md_link(f'Roadmap {public_id}', roadmap_link)}"
        # Source link to Message Center
        src_line = ""
        if message_id:
            src_line = f"Source: {_md_link(f'Message Center {message_id}', f'https://admin.microsoft.com/adminportal/home#/MessageCenter/{message_id}')}"
        meta = []
        if status:
            meta.append(f"Status: {status}")
        if release_date:
            meta.append(f"Release: {release_date}")
        if clouds:
            meta.append(f"Cloud(s): {clouds}")
        if last_modified:
            meta.append(f"Last Modified: {last_modified}")
        meta_line = " · ".join(meta)

        b = []
        b.append(title_line)
        if pills:
            b.append(f"\n**Products:** {pills}")
        if meta_line:
            b.append(f"\n{meta_line}")
        if src_line:
            b.append(f"\n{src_line}")

        # AI sections (placeholders)
        b.append("\n\n**Summary**\n\n_(summary pending)_")
        b.append("\n\n**What’s changing**\n\n_(details pending)_")
        b.append("\n\n**Impact and rollout**\n\n_(impact pending)_")
        b.append("\n\n**Action items**\n\n_(actions pending)_\n")

        return "\n".join(b)


# ---------- data model & helpers ----------

CLOUD_CANON = {
    "Worldwide (Standard Multi-Tenant)": "General",
    "Worldwide": "General",
    "General": "General",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
}

# Known master CSV headers produced by your fetcher
KNOWN_HEADERS = [
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


@dataclass
class FeatureRecord:
    public_id: str = ""
    title: str = ""
    source: str = ""  # graph | public-json | rss | seed
    product: str = ""
    status: str = ""
    last_modified: str = ""
    release_date: str = ""
    clouds: str = ""  # “General”, “GCC”, ...
    roadmap_link: str = ""
    message_id: str = ""


def _parse_date_soft(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _within_window(r: FeatureRecord, since: str | None, months: str | None) -> bool:
    if not since and not months:
        return True
    # Prefer LastModified, then ReleaseDate
    dt_s = _parse_date_soft(r.last_modified) or _parse_date_soft(r.release_date)
    if not dt_s:
        return False
    if since:
        sdt = _parse_date_soft(since)
        if sdt and dt_s < sdt:
            return False
    if months:
        try:
            m = int(months)
            cutoff = datetime.now(timezone.utc) - timedelta(days=30 * m)
            if dt_s < cutoff:
                return False
        except ValueError:
            pass
    return True


def _canon_cloud(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "General"  # treat blank as General so we don’t drop rows
    return CLOUD_CANON.get(s, s)


def _products_match(product: str, want: list[str]) -> bool:
    if not want:
        return True
    p = (product or "").lower()
    return any(w in p for w in want)


def _split_csv_like(s: str) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"[,\|;]", s)]
    return [p for p in parts if p]


def _row_to_feature(row: dict) -> FeatureRecord:
    # Map from master CSV names (and a few variants) to FeatureRecord
    def g(key: str, alts: Sequence[str] = ()) -> str:
        if key in row:
            return row[key] or ""
        for a in alts:
            if a in row:
                return row[a] or ""
        return ""

    # Primary mapping from your fetcher’s CSV
    return FeatureRecord(
        public_id=g("PublicId", ("public_id", "id")),
        title=g("Title", ("title",)),
        source=g("Source", ("source",)),
        product=g("Product_Workload", ("product", "workload", "Product", "Workload")),
        status=g("Status", ("status",)),
        last_modified=g("LastModified", ("last_modified", "Modified", "Updated")),
        release_date=g("ReleaseDate", ("release_date", "Release", "ETA")),
        clouds=_canon_cloud(g("Cloud_instance", ("clouds", "Cloud", "Clouds"))),
        roadmap_link=g("Official_Roadmap_link", ("roadmap_link", "Roadmap", "Link")),
        message_id=g("MessageId", ("message_id", "mcid", "MCID")),
    )


def _read_master_csv(path: str | Path) -> list[FeatureRecord]:
    p = Path(path)
    if not p.exists():
        print(f"[gen] master not found: {p}")
        return []
    rows: list[FeatureRecord] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for raw in r:
            rec = _row_to_feature({k.strip(): (v or "").strip() for k, v in raw.items()})
            # Ensure roadmap link if missing but we have an ID
            if not rec.roadmap_link and rec.public_id:
                rec.roadmap_link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rec.public_id}"
            rows.append(rec)
    print(f"[gen] read={len(rows)} from {p}")
    return rows


def _filter_cloud(rows: list[FeatureRecord], selected: list[str]) -> list[FeatureRecord]:
    if not selected:
        # Default to General
        selected = ["General"]
    selected_can = {_canon_cloud(c) for c in selected}
    out = [r for r in rows if _canon_cloud(r.clouds) in selected_can]
    print(f"[gen] after cloud filter ({sorted(selected_can)}): {len(out)}")
    return out


def _filter_products(rows: list[FeatureRecord], products: str | None) -> list[FeatureRecord]:
    want = [w.lower() for w in _split_csv_like(products or "")]
    if not want:
        return rows
    out = [r for r in rows if _products_match(r.product, want)]
    print(f"[gen] after products filter ({want}): {len(out)}")
    return out


def _filter_dates(rows: list[FeatureRecord], since: str | None, months: str | None) -> list[FeatureRecord]:
    out = [r for r in rows if _within_window(r, since, months)]
    print(f"[gen] after date filter (since={since}, months={months}): {len(out)}")
    return out


def _synthesize_missing_ids(ids: list[str]) -> list[FeatureRecord]:
    out: list[FeatureRecord] = []
    for pid in ids:
        pid = pid.strip()
        if not pid:
            continue
        out.append(
            FeatureRecord(
                public_id=pid,
                title=f"[{pid}]",
                source="seed",
                product="",
                status="",
                last_modified="",
                release_date="",
                clouds="General",
                roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pid}",
                message_id="",
            )
        )
    return out


def _order_forced_first(rows: list[FeatureRecord], forced_ids: list[str]) -> list[FeatureRecord]:
    if not forced_ids:
        return rows
    pos = {pid: i for i, pid in enumerate(forced_ids)}
    rows.sort(key=lambda r: (pos.get(r.public_id, 10_000_000), (r.last_modified or ""), r.title))
    return rows


def _make_toc(rows: list[FeatureRecord]) -> str:
    items = []
    for r in rows:
        anchor = re.sub(r"[^a-z0-9]+", "-", (r.title or f"[{r.public_id}]").lower()).strip("-")
        items.append(f"- [{r.title or r.public_id}](#{anchor})")
    if not items:
        return ""
    return "## Table of Contents\n\n" + "\n".join(items) + "\n"


# ---------- CLI ----------

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--master", required=True, help="Path to *_master.csv produced by fetch script")
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default=None)
    ap.add_argument("--months", default=None)
    ap.add_argument("--cloud", action="append", default=[], help="Repeatable. e.g. 'Worldwide (Standard Multi-Tenant)', 'GCC'")
    ap.add_argument("--products", default=None, help="Comma/pipe-separated keywords; blank=all")
    ap.add_argument("--forced-ids", default="", help="Comma-separated exact PublicId list (ordered)")
    return ap.parse_args(argv)


# ---------- MAIN ----------

def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    # Read and normalize
    all_rows = _read_master_csv(args.master)

    # Filters
    clouds = args.cloud[:] if args.cloud else ["General"]
    rows = _filter_cloud(all_rows, clouds)
    rows = _filter_products(rows, args.products)
    rows = _filter_dates(rows, args.since, args.months)

    # Forced IDs handling
    forced_ids = _split_csv_like(args.forced_ids)
    if forced_ids:
        have = {r.public_id for r in rows}
        missing = [pid for pid in forced_ids if pid not in have]
        if missing:
            synth = _synthesize_missing_ids(missing)
            rows = rows + synth
            print(f"[gen] synthesized {len(synth)} forced IDs not present in master: {missing}")
        rows = _order_forced_first(rows, forced_ids)

    print(f"[gen] final row count: {len(rows)}")

    # Output assembly
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = ", ".join(sorted({_canon_cloud(c) for c in clouds}))

    parts: list[str] = []
    parts.append(render_header(title=args.title, generated_utc=generated, cloud_display=cloud_display))
    parts.append(f"**Total features:** {len(rows)}\n")
    parts.append(_make_toc(rows))

    for r in rows:
        parts.append(
            render_feature_markdown(
                public_id=r.public_id,
                title=r.title or (f"[{r.public_id}]" if r.public_id else "(untitled)"),
                product=r.product,
                status=r.status,
                clouds=r.clouds,
                last_modified=r.last_modified,
                release_date=r.release_date,
                source=r.source,
                message_id=r.message_id,
                roadmap_link=r.roadmap_link,
            )
        )
        parts.append("\n---\n")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"[gen] wrote: {out_path}")


if __name__ == "__main__":
    main()
