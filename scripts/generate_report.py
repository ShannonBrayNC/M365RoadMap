#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

# --- Try UI helpers; fall back if not importable ---
try:
    from report_templates import (  # type: ignore
        render_header,
        render_feature_markdown,
    )
except Exception:
    def _md_link(text: str, url: str) -> str:
        return f"[{text}]({url})" if url else text

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
        pills = ""
        if product:
            parts = [p.strip() for p in re.split(r"[,/|]+", product) if p.strip()]
            if parts:
                pills = " ".join(f"`{p}`" for p in parts)

        title_line = f"**{title}**"
        if public_id:
            title_line += f"  \n{_md_link(f'Roadmap {public_id}', roadmap_link)}"

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

        b: list[str] = []
        b.append(title_line)
        if pills:
            b.append(f"\n**Products:** {pills}")
        if meta_line:
            b.append(f"\n{meta_line}")
        if src_line:
            b.append(f"\n{src_line}")

        b.append("\n\n**Summary**\n\n_(summary pending)_")
        b.append("\n\n**What’s changing**\n\n_(details pending)_")
        b.append("\n\n**Impact and rollout**\n\n_(impact pending)_")
        b.append("\n\n**Action items**\n\n_(actions pending)_\n")
        return "\n".join(b)

# --- Canon & datamodel ---

CLOUD_CANON = {
    "Worldwide (Standard Multi-Tenant)": "General",
    "Worldwide": "General",
    "General": "General",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
}

@dataclass
class FeatureRecord:
    public_id: str = ""
    title: str = ""
    source: str = ""   # graph | public-json | rss | seed
    product: str = ""
    status: str = ""
    last_modified: str = ""
    release_date: str = ""
    clouds: str = ""   # General | GCC | GCC High | DoD
    roadmap_link: str = ""
    message_id: str = ""

# --- small utils ---

def _canon_cloud(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "General"
    return CLOUD_CANON.get(s, s)

def _split_csv_like(s: str | None) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in re.split(r"[,\|;]", s) if p.strip()]

def _parse_date_soft(s: str | None):
    if not s:
        return None
    ss = s.strip()
    if not ss:
        return None
    try:
        if len(ss) == 10 and ss[4] == "-" and ss[7] == "-":
            return datetime(int(ss[0:4]), int(ss[5:7]), int(ss[8:10]), tzinfo=timezone.utc)
        return datetime.fromisoformat(ss.replace("Z", "+00:00"))
    except Exception:
        return None

def _products_match(product: str, want_lower: list[str]) -> bool:
    if not want_lower:
        return True
    p = (product or "").lower()
    return any(w in p for w in want_lower)

# --- CSV ingestion ---

def _row_to_feature(row: dict[str, str]) -> FeatureRecord:
    def g(*keys: str) -> str:
        for k in keys:
            if k in row and row[k] is not None:
                return row[k].strip()
        return ""

    # cover many aliases seen in different writers
    public_id   = g("PublicId", "public_id", "Id", "ID")
    title       = g("Title", "title", "Name")
    source      = g("Source", "source")
    product     = g("Product_Workload", "Product/Workload", "product", "workload", "Product", "Workload")
    status      = g("Status", "status")
    last_mod    = g("LastModified", "last_modified", "Modified", "Updated", "Last Modified")
    release     = g("ReleaseDate", "release_date", "Release", "ETA", "Release Date")
    cloud_val   = g("Cloud_instance", "Cloud instance", "CloudInstance", "clouds", "Cloud", "Clouds")
    roadmap     = g("Official_Roadmap_link", "roadmap_link", "Roadmap", "Link", "OfficialRoadmap")
    message_id  = g("MessageId", "message_id", "mcid", "MCID", "Message ID")

    clouds = _canon_cloud(cloud_val)
    if not roadmap and public_id:
        roadmap = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}"

    return FeatureRecord(
        public_id=public_id,
        title=title or (f"[{public_id}]" if public_id else ""),
        source=source,
        product=product,
        status=status,
        last_modified=last_mod,
        release_date=release,
        clouds=clouds,
        roadmap_link=roadmap,
        message_id=message_id,
    )

def _read_master_csv(path: str | Path) -> list[FeatureRecord]:
    p = Path(path)
    if not p.exists():
        print(f"[gen] master not found: {p}")
        return []
    rows: list[FeatureRecord] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        if rdr.fieldnames:
            print(f"[gen] headers: {rdr.fieldnames}")
        for raw in rdr:
            norm = {k.strip(): (v or "").strip() for k, v in raw.items()}
            rows.append(_row_to_feature(norm))
    print(f"[gen] read={len(rows)} from {p}")
    return rows

# --- filters ---

def _filter_cloud(rows: list[FeatureRecord], selected: list[str]) -> list[FeatureRecord]:
    sel = {_canon_cloud(c) for c in (selected or ["General"])}
    out = [r for r in rows if _canon_cloud(r.clouds) in sel]
    print(f"[gen] after cloud filter ({sorted(sel)}): {len(out)}")
    return out

def _filter_products(rows: list[FeatureRecord], products: str | None) -> list[FeatureRecord]:
    want = [w.lower() for w in _split_csv_like(products)]
    if not want:
        return rows
    out = [r for r in rows if _products_match(r.product, want)]
    print(f"[gen] after products filter ({want}): {len(out)}")
    return out

def _filter_dates(rows: list[FeatureRecord], since: str | None, months: str | None) -> list[FeatureRecord]:
    if not since and not months:
        return rows
    out: list[FeatureRecord] = []
    since_dt = _parse_date_soft(since) if since else None
    months_cut = None
    if months:
        try:
            m = int(months)
            months_cut = datetime.now(timezone.utc) - timedelta(days=30*m)
        except ValueError:
            pass
    for r in rows:
        dtv = _parse_date_soft(r.last_modified) or _parse_date_soft(r.release_date)
        if not dtv:
            continue
        if since_dt and dtv < since_dt:
            continue
        if months_cut and dtv < months_cut:
            continue
        out.append(r)
    print(f"[gen] after date filter (since={since}, months={months}): {len(out)}")
    return out

# --- forced ids ---

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

# --- toc ---

def _make_toc(rows: list[FeatureRecord]) -> str:
    items = []
    for r in rows:
        name = r.title or r.public_id or "(untitled)"
        anchor = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        items.append(f"- [{name}](#{anchor})")
    return ("## Table of Contents\n\n" + "\n".join(items) + "\n") if items else ""

# --- cli ---

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default=None)
    ap.add_argument("--months", default=None)
    ap.add_argument("--cloud", action="append", default=[], help="Repeatable; e.g. 'Worldwide (Standard Multi-Tenant)', 'GCC'")
    ap.add_argument("--products", default=None, help="Comma/pipe list; blank = all")
    ap.add_argument("--forced-ids", default="", help="Comma-separated exact PublicId list (ordered)")
    return ap.parse_args(argv)

# --- main ---

def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    all_rows = _read_master_csv(args.master)

    # First pass filters
    clouds = args.cloud[:] if args.cloud else ["General"]
    rows = _filter_cloud(all_rows, clouds)
    rows = _filter_products(rows, args.products)
    rows = _filter_dates(rows, args.since, args.months)

    # Progressive fallbacks if empty (only relax filters, never add rows silently)
    if not rows and (args.products or args.since or args.months):
        print("[gen] WARNING: filters yielded 0 rows → relaxing products/date filters")
        rows = _filter_cloud(all_rows, clouds)  # cloud only

    if not rows and clouds:
        print("[gen] WARNING: cloud filter still 0 → relaxing cloud filter (all clouds)")
        rows = all_rows[:]  # no filters

    # Forced IDs
    forced_ids = _split_csv_like(args.forced_ids)
    if forced_ids:
        have = {r.public_id for r in rows}
        missing = [pid for pid in forced_ids if pid not in have]
        if missing:
            synth = _synthesize_missing_ids(missing)
            rows += synth
            print(f"[gen] synthesized {len(synth)} forced IDs not present in master: {missing}")
        rows = _order_forced_first(rows, forced_ids)

    print(f"[gen] final row count: {len(rows)}")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = ", ".join(sorted({_canon_cloud(c) for c in (clouds or ['General'])}))

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
