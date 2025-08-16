#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set


# --- import helpers ---------------------------------------------------------

def _try_import_report_templates():
    """
    Try to import report_templates from either scripts.report_templates or
    report_templates. Return a dict of callables/objects, with graceful fallbacks.
    """
    mod = {}
    # Make sure repo root and scripts dir are on path
    here = os.path.abspath(os.path.dirname(__file__))
    repo_root = os.path.abspath(os.path.join(here, ".."))
    for p in (repo_root, here):
        if p not in sys.path:
            sys.path.insert(0, p)

    # Try "scripts.report_templates" first
    try:
        from scripts.report_templates import (  # type: ignore
            FeatureRecord as _FR,
            render_header as _render_header,
            render_feature_markdown as _render_feature_markdown,
            normalize_clouds as _normalize_clouds,
        )
        mod["FeatureRecord"] = _FR
        mod["render_header"] = _render_header
        mod["render_feature_markdown"] = _render_feature_markdown
        mod["normalize_clouds"] = _normalize_clouds
        return mod
    except Exception:
        pass

    # Then try local "report_templates"
    try:
        from report_templates import (  # type: ignore
            FeatureRecord as _FR,
            render_header as _render_header,
            render_feature_markdown as _render_feature_markdown,
            normalize_clouds as _normalize_clouds,
        )
        mod["FeatureRecord"] = _FR
        mod["render_header"] = _render_header
        mod["render_feature_markdown"] = _render_feature_markdown
        mod["normalize_clouds"] = _normalize_clouds
        return mod
    except Exception:
        pass

    # Fallbacks (minimal local implementations)
    @dataclass
    class _FR:  # minimal, snake_case
        public_id: str
        title: str
        product: str = ""
        status: str = ""
        last_modified: str = ""
        release_date: str = ""
        clouds: Set[str] = field(default_factory=set)
        roadmap_link: str = ""
        message_id: str = ""
        source: str = ""

    def _render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
        return (
            f"{title}\n"
            f"Generated {generated_utc}\n\n"
            f"{title} Generated {generated_utc} Cloud filter: {cloud_display}\n"
        )

    def _render_feature_markdown(rec: _FR, ai_sections: Optional[dict[str, str]] = None) -> str:
        ai_sections = ai_sections or {}
        summary = ai_sections.get("summary", "Summary (summary pending)")
        changes = ai_sections.get("changes", "What’s changing (details pending)")
        impact = ai_sections.get("impact", "Impact and rollout (impact pending)")
        actions = ai_sections.get("actions", "Action items (actions pending)")

        cloud_disp = ", ".join(sorted(rec.clouds)) if rec.clouds else "—"
        rm = rec.roadmap_link or (f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rec.public_id}" if rec.public_id else "")
        parts = [
            f"[{rec.public_id}] {rec.title} "
            f"Product/Workload: {rec.product or '—'} "
            f"Status: {rec.status or '—'} "
            f"Cloud(s): {cloud_disp} "
            f"Last Modified: {rec.last_modified or '—'} "
            f"Release Date: {rec.release_date or '—'} "
            f"Source: {rec.source or '—'} "
            f"Message ID: {rec.message_id or '—'} "
            f"Official Roadmap: {rm}".strip(),
            "",
            summary,
            "",
            changes,
            "",
            impact,
            "",
            actions,
            "",
        ]
        return "\n".join(parts)

    def _normalize_clouds(val: Iterable[str] | str | None) -> Set[str]:
        CANON = {
            "worldwide (standard multi-tenant)": "General",
            "worldwide": "General",
            "general": "General",
            "commercial": "General",
            "gcc": "GCC",
            "gcc high": "GCC High",
            "gcch": "GCC High",
            "dod": "DoD",
            "department of defense": "DoD",
        }
        if not val:
            return set()
        if isinstance(val, str):
            vals = [val]
        else:
            vals = list(val)
        out: Set[str] = set()
        for v in vals:
            k = (v or "").strip().lower()
            if not k:
                continue
            out.add(CANON.get(k, v.strip()))
        return out

    mod["FeatureRecord"] = _FR
    mod["render_header"] = _render_header
    mod["render_feature_markdown"] = _render_feature_markdown
    mod["normalize_clouds"] = _normalize_clouds
    return mod


_rt = _try_import_report_templates()
FeatureRecord = _rt["FeatureRecord"]
render_header = _rt["render_header"]
render_feature_markdown = _rt["render_feature_markdown"]
normalize_clouds = _rt["normalize_clouds"]


# --- utilities --------------------------------------------------------------

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
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m", "%Y/%m", "%b %d %Y", "%b %Y"):
        try:
            d = dt.datetime.strptime(s, fmt)
            return d.date()
        except Exception:
            continue
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
    Map the CSV (which may use Title/PublicId/Cloud_instance/etc.) to our FeatureRecord (snake_case).
    Be tolerant of missing fields.
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

    # If we have an ID but no roadmap link, synthesize it.
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
                # Skip malformed lines, but don't crash the report
                continue
    print(f"[gen] read={len(rows)} from {path}")
    return rows


def _filter_by_cloud(rows: Sequence[FeatureRecord], clouds: Sequence[str] | None) -> list[FeatureRecord]:
    if not clouds:
        return list(rows)
    selected: Set[str] = normalize_clouds(clouds)
    if not selected:
        return list(rows)

    def include(rec: FeatureRecord) -> bool:
        if not rec.clouds:
            # Treat items with no cloud stamped as eligible (common in CSV)
            return True
        return bool(rec.clouds & selected)

    out = [r for r in rows if include(r)]
    disp = sorted(selected)
    print(f"[gen] after cloud filter ({disp}): {len(out)}")
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
        # Prefer LastModified; fallback to ReleaseDate
        d = _parse_date_soft(r.last_modified) or _parse_date_soft(r.release_date)
        if _date_in_window(d, since=d_since, months=months):
            out.append(r)
    if d_since or months:
        print(f"[gen] after time filter (since={d_since}, months={months}): {len(out)}")
    return out


def _rule_based_sections(rec: FeatureRecord) -> dict[str, str]:
    """Readable defaults for AI-like sections."""
    rid = rec.public_id
    title = rec.title or f"[{rid}]"
    product = rec.product or "Microsoft 365"
    status = rec.status or "—"
    clouds = ", ".join(sorted(rec.clouds)) if getattr(rec, "clouds", None) else "—"
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

    changes_bits: list[str] = []
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

    impact_bits: list[str] = []
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

    actions_bits: list[str] = []
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


# --- main -------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="Report title")
    ap.add_argument("--master", required=True, help="Input master CSV")
    ap.add_argument("--out", required=True, help="Output markdown path")
    ap.add_argument("--since", default="", help="Only include items on/after YYYY-MM-DD")
    ap.add_argument("--months", type=int, default=None, help="Only include items within last N months")
    ap.add_argument("--cloud", action="append", help="Cloud display (e.g., 'Worldwide (Standard Multi-Tenant)', 'GCC')", default=None)
    ap.add_argument("--products", default="", help="Comma/pipe separated product filter (e.g., Teams,SharePoint)")
    ap.add_argument("--forced-ids", default="", help="Comma-separated PublicId list to force/include (ordered)")
    args = ap.parse_args()

    all_rows = _read_master_csv(args.master)

    # Time & cloud filters
    all_rows = _filter_by_time(all_rows, since=args.since or None, months=args.months)
    rows = _filter_by_cloud(all_rows, args.cloud)

    # Product filter
    rows = _filter_by_products(rows, _split_csv_like(args.products))

    # Forced IDs: ensure presence and exact ordering
    forced_list = _split_csv_like(args.forced_ids)
    forced_set = set(forced_list)
    if forced_list:
        # Build index of existing rows
        by_id = {r.public_id: r for r in rows}
        synthesized: list[FeatureRecord] = []
        for fid in forced_list:
            synthesized.append(by_id.get(fid) or _synthesize_placeholder(fid))
        # Append the rest (excluding any that are already in forced list)
        remainder = [r for r in rows if r.public_id not in forced_set]
        rows = synthesized + remainder

    print(f"[gen] final row count: {len(rows)}")

    # Cloud display for header
    selected_clouds = normalize_clouds(args.cloud or [])
    cloud_display = ", ".join(sorted(selected_clouds)) if selected_clouds else "All"

    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Build markdown
    parts: list[str] = []
    parts.append(render_header(title=args.title, generated_utc=generated, cloud_display=cloud_display))
    parts.append(f"\nTotal features: {len(rows)}\n")

    for rec in rows:
        ai = _rule_based_sections(rec)
        parts.append(render_feature_markdown(rec, ai_sections=ai))

    md = "\n".join(parts).rstrip() + "\n"
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[gen] wrote: {args.out} (features={len(rows)})")


if __name__ == "__main__":
    main()
