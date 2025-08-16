#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from typing import Iterable, Optional, Sequence, Set, List

# Ensure we can import sibling "scripts.report_templates" or local "report_templates"
_HERE = os.path.abspath(os.path.dirname(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Prefer the project's report_templates; fallback to local if needed
try:
    from scripts.report_templates import (  # type: ignore
        FeatureRecord,
        render_header,
        render_feature_markdown,
        normalize_clouds,
    )
except Exception:
    from report_templates import (  # type: ignore
        FeatureRecord,
        render_header,
        render_feature_markdown,
        normalize_clouds,
    )


def _split_csv_like(s: str | None) -> list[str]:
    if not s:
        return []
    raw = s.replace("|", ",").replace(";", ",")
    items = [t.strip() for t in raw.split(",")]
    return [t for t in items if t]


def _parse_date_soft(s: str | None) -> Optional[dt.date]:
    if not s:
        return None
    s = s.strip()
    # Try a few common shapes we see in roadmap exports
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m", "%Y/%m", "%b %d %Y", "%b %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _date_in_window(d: Optional[dt.date], *, since: Optional[dt.date], months: Optional[int]) -> bool:
    if not since and not months:
        return True
    if not d:
        return False
    if since and d < since:
        return False
    if months:
        cutoff = dt.date.today() - dt.timedelta(days=months * 30)
        if d < cutoff:
            return False
    return True


def _map_row_to_record(row: dict[str, str]) -> FeatureRecord:
    """
    Map CSV headers like:
      PublicId, Title, Source, Product_Workload, Status, LastModified,
      ReleaseDate, Cloud_instance, Official_Roadmap_link, MessageId
    into our FeatureRecord (snake_case).
    """
    def g(keys: Sequence[str], default: str = "") -> str:
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return default

    public_id = g(["PublicId", "public_id", "Id", "RoadmapId"]).strip()
    title = g(["Title", "title"]).strip() or f"[{public_id}]"
    product = g(["Product_Workload", "product", "Workload"]).strip()
    status = g(["Status", "status"]).strip()
    last_modified = g(["LastModified", "last_modified"]).strip()
    release_date = g(["ReleaseDate", "release_date"]).strip()
    cloud_raw = g(["Cloud_instance", "cloud", "Clouds"]).strip()
    roadmap_link = g(["Official_Roadmap_link", "roadmap_link", "RoadmapLink"]).strip()
    message_id = g(["MessageId", "message_id"]).strip()
    source = g(["Source", "source"]).strip()

    clouds: Set[str] = set()
    if cloud_raw:
        clouds = normalize_clouds(cloud_raw)

    if public_id and not roadmap_link:
        roadmap_link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}"

    return FeatureRecord(
        public_id=public_id,
        title=title,
        product=product,
        status=status,
        last_modified=last_modified,
        release_date=release_date,
        clouds=clouds,
        roadmap_link=roadmap_link,
        message_id=message_id,
        source=source,
    )


def _read_master_csv(path: str) -> list[FeatureRecord]:
    rows: list[FeatureRecord] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            try:
                rows.append(_map_row_to_record(row))
            except Exception:
                # Skip malformed lines
                continue
    print(f"[gen] read={len(rows)} from {path}")
    return rows


def _filter_by_cloud(rows: Sequence[FeatureRecord], clouds: Sequence[str] | None) -> list[FeatureRecord]:
    if not clouds:
        print(f"[gen] after cloud filter (All): {len(rows)}")
        return list(rows)

    selected = normalize_clouds(clouds)
    if not selected:
        print(f"[gen] after cloud filter (All): {len(rows)}")
        return list(rows)

    def include(rec: FeatureRecord) -> bool:
        if not rec.clouds:
            # treat items with no cloud stamp as eligible
            return True
        return bool(rec.clouds & selected)

    out = [r for r in rows if include(r)]
    print(f"[gen] after cloud filter ({sorted(selected)}): {len(out)}")
    return out


def _filter_by_products(rows: Sequence[FeatureRecord], products: Sequence[str] | None) -> list[FeatureRecord]:
    tokens = [t.lower() for t in (products or []) if t.strip()]
    if not tokens:
        return list(rows)

    def matches(r: FeatureRecord) -> bool:
        hay = f"{r.product} {r.title}".lower()
        return any(t in hay for t in tokens)

    out = [r for r in rows if matches(r)]
    print(f"[gen] after product filter ({tokens}): {len(out)}")
    return out


def _filter_by_time(rows: Sequence[FeatureRecord], *, since: Optional[str], months: Optional[int]) -> list[FeatureRecord]:
    d_since = _parse_date_soft(since) if since else None
    out: list[FeatureRecord] = []
    for r in rows:
        d = _parse_date_soft(r.last_modified) or _parse_date_soft(r.release_date)
        if _date_in_window(d, since=d_since, months=months):
            out.append(r)
    if d_since or months:
        print(f"[gen] after time filter (since={d_since}, months={months}): {len(out)}")
    return out


def _rule_based_sections(rec: FeatureRecord) -> dict[str, str]:
    rid = rec.public_id
    title = rec.title or f"[{rid}]"
    product = rec.product or "Microsoft 365"
    status = rec.status or "—"
    clouds = ", ".join(sorted(rec.clouds)) if rec.clouds else "—"
    last_mod = rec.last_modified or "—"
    rel = rec.release_date or "—"
    source = rec.source or "—"

    updated_hint = "updated" in title.lower()
    is_teams = "teams" in product.lower()
    is_sharepoint = ("sharepoint" in product.lower()) or ("onedrive" in product.lower())
    is_outlook = ("outlook" in product.lower()) or ("exchange" in product.lower())
    is_purview = "purview" in product.lower()
    is_viva = "viva" in product.lower()

    summary = (
        f"{product}: {title}."
        f"{' (Updated)' if updated_hint else ''} "
        f"Status: {status}. Clouds: {clouds}. "
        f"Last modified: {last_mod}; planned release: {rel}. Source: {source}."
    ).strip()

    changes_bits: List[str] = []
    if updated_hint:
        changes_bits.append("This roadmap item has been updated since its original posting.")
    if is_teams:
        changes_bits.append("The change affects Microsoft Teams meeting/chat/channel experiences.")
    if is_sharepoint:
        changes_bits.append("The change impacts SharePoint/OneDrive content and file experiences.")
    if is_outlook:
        changes_bits.append("The change impacts Outlook/Exchange mail and calendar experiences.")
    if is_purview:
        changes_bits.append("This concerns compliance, governance, or data security scenarios in Purview.")
    if is_viva:
        changes_bits.append("This affects employee experience modules in Microsoft Viva.")
    if not changes_bits:
        changes_bits.append("This is a feature/update tracked in the Microsoft 365 roadmap.")
    changes = " ".join(changes_bits)

    impact_bits: List[str] = []
    if is_teams:
        impact_bits.append("Users may notice UI or behavior changes in Teams; update training as needed.")
    if is_sharepoint:
        impact_bits.append("Admins/content owners should validate sharing, file handling, and site templates.")
    if is_outlook:
        impact_bits.append("Communicate changes to mail/calendar behaviors and consider Outlook policy impacts.")
    if is_purview:
        impact_bits.append("Review DLP/retention/sensitivity policies for side effects and required updates.")
    if not impact_bits:
        impact_bits.append("Assess change management needs and adjust communications if end-user experience changes.")
    impact = " ".join(impact_bits)

    actions_bits: List[str] = []
    actions_bits.append("Track rollout via the official roadmap link and any related Message center posts.")
    if is_teams or is_sharepoint or is_outlook:
        actions_bits.append("Validate tenant policies/configuration in a test ring before broad rollout.")
    if is_purview:
        actions_bits.append("Evaluate compliance posture and update policies as appropriate.")
    actions_bits.append("Prepare short end-user and helpdesk notes for awareness.")
    actions = " ".join(actions_bits)

    return {"summary": summary, "changes": changes, "impact": impact, "actions": actions}


def _synthesize_placeholder(fid: str) -> FeatureRecord:
    return FeatureRecord(
        public_id=fid,
        title=f"[{fid}]",
        product="",
        status="",
        last_modified="",
        release_date="",
        clouds=set(),
        roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={fid}",
        message_id="",
        source="seed",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default="")
    ap.add_argument("--months", type=int, default=None)
    ap.add_argument("--cloud", action="append", default=None,
                    help="e.g. 'Worldwide (Standard Multi-Tenant)', 'GCC', 'GCC High', 'DoD'")
    ap.add_argument("--products", default="", help="Comma/pipe separated tokens (e.g. Teams|SharePoint)")
    ap.add_argument("--forced-ids", default="", help="Comma-separated PublicId list to force/include (ordered)")
    args = ap.parse_args()

    # Load & map
    all_rows = _read_master_csv(args.master)

    # Time filter first (reduces volume early)
    all_rows = _filter_by_time(all_rows, since=args.since or None, months=args.months)

    # Cloud & products
    rows = _filter_by_cloud(all_rows, args.cloud)
    rows = _filter_by_products(rows, _split_csv_like(args.products))

    # Forced ordering / synthesized placeholders
    forced_list = _split_csv_like(args.forced_ids)
    if forced_list:
        index = {r.public_id: r for r in rows}
        forced_part = [index.get(fid) or _synthesize_placeholder(fid) for fid in forced_list]
        remainder = [r for r in rows if r.public_id not in set(forced_list)]
        rows = forced_part + remainder

    print(f"[gen] final row count: {len(rows)}")

    # Header cloud display
    selected_clouds = normalize_clouds(args.cloud or [])
    cloud_display = ", ".join(sorted(selected_clouds)) if selected_clouds else "All"

    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    parts: list[str] = []
    parts.append(render_header(title=args.title, generated_utc=generated, cloud_display=cloud_display))
    parts.append(f"\nTotal features: {len(rows)}\n")

    for rec in rows:
        ai = _rule_based_sections(rec)
        parts.append(render_feature_markdown(rec, ai_sections=ai))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(parts).rstrip() + "\n")
    print(f"[gen] wrote: {args.out} (features={len(rows)})")


if __name__ == "__main__":
    main()
