#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from textwrap import dedent
from typing import Iterable, List, Optional, Sequence
import re
from typing import Sequence
import sys

# normalize_clouds helper (import, with robust fallback)
try:
    from report_templates import normalize_clouds
except Exception:
    def normalize_clouds(values: list[str] | str) -> set[str]:  # very small fallback
        if isinstance(values, str):
            values = [values]
        canon = {
            "worldwide (standard multi-tenant)": "General",
            "general": "General",
            "gcc": "GCC",
            "gcc high": "GCC High",
            "dod": "DoD",
        }
        out: set[str] = set()
        for v in values or []:
            k = (v or "").strip().lower()
            out.add(canon.get(k, (v or "").strip()))
        return out


# --- FeatureRecord import (with fallback) ------------------------------------
try:
    # Preferred: use the shared model from report_templates if present
    from report_templates import FeatureRecord  # type: ignore[attr-defined]
except Exception:
    # Fallback: lightweight local definition that matches fields used here
    from dataclasses import dataclass, field
    from typing import List

    @dataclass
    class FeatureRecord:
        public_id: str
        title: str
        product: str = ""
        status: str = ""
        last_modified: str = ""
        release_date: str = ""
        clouds: List[str] = field(default_factory=lambda: ["General"])
        roadmap_link: str = ""
        source: str = ""
        message_id: str = ""
# ---------------------------------------------------------------------------



# --- Rendering helpers import (with fallback) --------------------------------
try:
    # Prefer the shared implementations
    from report_templates import render_header, render_feature_markdown  # type: ignore[attr-defined]
except Exception:
    # Minimal fallbacks so the script still runs end-to-end
    def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
        # Matches the signature used by generate_report.py
        lines = [
            "# Roadmap Report",
            f"Generated {generated_utc}",
            "",
            f"{title} Generated {generated_utc} Cloud filter: {cloud_display}",
            "",
        ]
        return "\n".join(lines)

    def render_feature_markdown(fr) -> str:
        # Very lightweight rendering; replace with your rich template if desired
        rid = fr.public_id
        title = fr.title or f"[{rid}]"
        product = fr.product or "—"
        status = fr.status or "—"
        clouds = ", ".join(fr.clouds) if getattr(fr, "clouds", None) else "—"
        last_mod = fr.last_modified or "—"
        rel = fr.release_date or "—"
        src = fr.source or "—"
        msg = fr.message_id or "—"
        link = fr.roadmap_link or f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}"

        body = [
            f"[{rid}] {title}",
            f"Product/Workload: {product}  Status: {status}  Cloud(s): {clouds}  "
            f"Last Modified: {last_mod}  Release Date: {rel}  Source: {src}  "
            f"Message ID: {msg}  Official Roadmap: {link}",
            "",
            "Summary (summary pending)",
            "",
            "What’s changing (details pending)",
            "",
            "Impact and rollout (impact pending)",
            "",
            "Action items (actions pending)",
            "",
        ]
        return "\n".join(body)
# -----------------------------------------------------------------------------


def _row_to_feature(row: dict[str, str]) -> FeatureRecord:
    """
    Convert a CSV row (with headers like PublicId, Product_Workload, Cloud_instance, etc.)
    into a FeatureRecord. Handles common header variants and normalizes clouds.
    """
    def g(*names: str) -> str:
        for n in names:
            if n in row and row[n] is not None:
                v = str(row[n]).strip()
                if v:
                    return v
        return ""

    # Public ID (required-ish; empty rows are skipped by caller)
    public_id = g("PublicId", "public_id", "Id", "ID")

    # Clouds: split on common separators then normalize to canonical short names
    clouds_raw = g("Cloud_instance", "Clouds", "Cloud", "CloudInstance")
    cloud_tokens: list[str] = []
    if clouds_raw:
        cloud_tokens = [t.strip() for t in re.split(r"[|,;/]+", clouds_raw) if t.strip()]
    clouds_norm = list(normalize_clouds(cloud_tokens)) if cloud_tokens else []

    return FeatureRecord(
        public_id=public_id,
        title=g("Title", "title", "Name"),
        product=g("Product_Workload", "Product", "Workload"),
        status=g("Status"),
        clouds=clouds_norm,
        last_modified=g("LastModified", "Last Modified", "Modified"),
        release_date=g("ReleaseDate", "Release Date"),
        source=g("Source"),
        message_id=g("MessageId", "Message ID", "MC_ID", "MCId"),
        roadmap_link=g("Official_Roadmap_link", "Roadmap", "RoadmapLink"),
    )


def _read_master_csv(path: str) -> list[FeatureRecord]:
    def _get(rec: dict[str, str], *names: str) -> str:
        # try exact keys first
        for n in names:
            if n in rec and rec[n] is not None:
                v = str(rec[n]).strip()
                if v:
                    return v
        # fallback: case-insensitive
        lower = {k.lower(): k for k in rec.keys()}
        for n in names:
            k = lower.get(n.lower())
            if k:
                v = str(rec[k] or "").strip()
                if v:
                    return v
        return ""

    rows: list[FeatureRecord] = []
    with open(path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for rec in rdr:
            public_id = _get(rec, "PublicId", "public_id", "Id")
            title = _get(rec, "Title", "title") or (f"[{public_id}]" if public_id else "")
            product = _get(rec, "Product_Workload", "Product", "Workload", "product")
            status = _get(rec, "Status", "status")
            last_modified = _get(rec, "LastModified", "last_modified")
            release_date = _get(rec, "ReleaseDate", "release_date")
            source = _get(rec, "Source", "source") or "graph"
            message_id = _get(rec, "MessageId", "message_id")
            roadmap_link = _get(
                rec, "Official_Roadmap_link", "official_roadmap_link", "Roadmap", "roadmap_link"
            )

            clouds_raw = _get(rec, "Cloud_instance", "Clouds")
            if clouds_raw:
                parts = [p.strip() for p in re.split(r"[|,;/]+", clouds_raw) if p.strip()]
                try:
                    clouds = sorted(normalize_clouds(parts))
                except Exception:
                    clouds = parts
            else:
                # IMPORTANT: treat blank as General
                clouds = ["General"]

            rows.append(
                FeatureRecord(
                    public_id=public_id,
                    title=title,
                    product=product,
                    status=status,
                    last_modified=last_modified,
                    release_date=release_date,
                    clouds=clouds,
                    roadmap_link=roadmap_link,
                    source=source,
                    message_id=message_id,
                )
            )

    # tiny debug breadcrumb
    print(f"[gen] read={len(rows)} from {path}", file=sys.stderr)
    return rows



    rows: List[FeatureRecord] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            # Be tolerant of missing columns
            def g(k: str) -> str:
                v = r.get(k)
                return (v or "").strip()

            rows.append(
                FeatureRecord(
                    PublicId=g("PublicId"),
                    Title=g("Title"),
                    Source=g("Source"),
                    Product_Workload=g("Product_Workload"),
                    Status=g("Status"),
                    LastModified=g("LastModified"),
                    ReleaseDate=g("ReleaseDate"),
                    Cloud_instance=g("Cloud_instance"),
                    Official_Roadmap_link=g("Official_Roadmap_link"),
                    MessageId=g("MessageId"),
                )
            )
    return rows


# ----------------------------
# Filters & helpers
# ----------------------------

def _cloud_display_from_args(clouds: Optional[Sequence[str]]) -> str:
    """
    Produce a compact cloud label for the report header.
    If blank/None → 'General'. If only Worldwide → 'General'. Else CSV of clouds.
    """
    if not clouds:
        return "General"
    # Preserve order, remove dups
    uniq = list(dict.fromkeys([c for c in clouds if c and c.strip()]))
    if not uniq:
        return "General"
    if len(uniq) == 1 and uniq[0] == "Worldwide (Standard Multi-Tenant)":
        return "General"
    return ", ".join(uniq)


def _filter_by_cloud(rows: list[FeatureRecord], clouds: Sequence[str] | None) -> list[FeatureRecord]:
    """
    Filter FeatureRecord objects by cloud. Prefers the pre-parsed FeatureRecord.clouds (list[str]).
    Falls back to parsing a Cloud_instance string if present (for legacy/mixed inputs).
    """
    if not clouds:
        return rows

    # Build canonical include set from the requested clouds
    include: set[str] = set()
    for c in clouds:
        if not c:
            continue
        try:
            canon = normalize_clouds([c])  # modern signature returns set[str]
        except TypeError:
            canon = normalize_clouds(c)    # tolerate older signature
        if isinstance(canon, set):
            include |= {s.strip() for s in canon if s.strip()}
        elif isinstance(canon, str):
            if canon.strip():
                include.add(canon.strip())

    if not include:
        return rows

    def row_clouds(r: FeatureRecord) -> set[str]:
        # Preferred: FeatureRecord.clouds already normalized upstream
        cl = getattr(r, "clouds", None)
        if cl:
            return set(cl)

        # Fallback: parse a raw Cloud_instance if present (legacy rows)
        raw = ""
        if isinstance(r, dict):  # super defensive if any dict sneaks in
            raw = str(r.get("Cloud_instance", "")).strip()
        else:
            raw = str(getattr(r, "Cloud_instance", "") or "").strip()

        if not raw:
            return set()

        # Split common separators and normalize
        parts = [p.strip() for p in re.split(r"[|,;/]+", raw) if p.strip()]
        try:
            return set(normalize_clouds(parts))  # type: ignore[arg-type]
        except Exception:
            return set(parts)

    return [r for r in rows if row_clouds(r) & include]
def _filter_by_cloud(rows: list[FeatureRecord], clouds: Sequence[str] | None) -> list[FeatureRecord]:
    if not clouds:
        return rows

    include: set[str] = set()
    for c in clouds:
        if not c:
            continue
        try:
            canon = normalize_clouds([c])
        except TypeError:
            canon = normalize_clouds(c)  # tolerate older signatures
        if isinstance(canon, set):
            include |= {s for s in canon if s}
        elif isinstance(canon, str) and canon.strip():
            include.add(canon.strip())

    if not include:
        return rows

    def row_clouds(r: FeatureRecord) -> set[str]:
        cl = getattr(r, "clouds", None)
        if cl:
            return set([s for s in cl if s])

        # ultra-defensive legacy fallback
        raw = getattr(r, "Cloud_instance", "") or ""
        if not raw:
            return {"General"}  # IMPORTANT: blank → General
        parts = [p.strip() for p in re.split(r"[|,;/]+", raw) if p.strip()]
        try:
            return set(normalize_clouds(parts))
        except Exception:
            return set(parts)

    out = [r for r in rows if row_clouds(r) & include]
    print(f"[gen] after cloud filter ({sorted(include)}): {len(out)}", file=sys.stderr)
    return out



def _parse_products_arg(products: Optional[str]) -> List[str]:
    """
    Accept comma or pipe delimited. Blank → [] (means 'all').
    """
    if not products:
        return []
    raw = [t.strip() for t in products.replace("|", ",").split(",")]
    return [t for t in raw if t]


def _filter_by_products(rows: list[FeatureRecord], products_csv: str | None) -> list[FeatureRecord]:
    if not products_csv:
        return rows
    wanted = {p.strip().lower() for p in re.split(r"[|,;]+", products_csv) if p.strip()}
    if not wanted:
        return rows

    def match(r: FeatureRecord) -> bool:
        hay = (r.product or "").lower()
        return any(tok in hay for tok in wanted)

    out = [r for r in rows if match(r)]
    print(f"[gen] after product filter ({sorted(wanted)}): {len(out)}", file=sys.stderr)
    return out


def _parse_forced_ids(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


def _synthesize_row(public_id: str) -> FeatureRecord:
    link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}"
    return FeatureRecord(
        PublicId=public_id,
        Title=f"[{public_id}]",
        Source="manual",
        Product_Workload="",
        Status="",
        LastModified="",
        ReleaseDate="",
        Cloud_instance="",
        Official_Roadmap_link=link,
        MessageId="",
    )


def _apply_forced_ids(rows: Sequence[FeatureRecord], forced_ids: Sequence[str]) -> List[FeatureRecord]:
    """
    Order results by forced_ids; synthesize rows for any ID not found in master.
    If forced_ids is empty, return rows unchanged.
    """
    if not forced_ids:
        return list(rows)
    by_id = {r.PublicId: r for r in rows}
    ordered: List[FeatureRecord] = []
    seen = set()
    for pid in forced_ids:
        rec = by_id.get(pid)
        if rec:
            ordered.append(rec)
            seen.add(pid)
        else:
            ordered.append(_synthesize_row(pid))
    # Optionally append the rest (not in forced list). Here we keep only the forced set.
    return ordered


# ----------------------------
# AI & deterministic sections
# ----------------------------

def _ai_available(args) -> bool:
    return (not args.ai_off) and bool(os.getenv("OPENAI_API_KEY"))


def _rule_based_sections(rec: FeatureRecord) -> tuple[str, str, str, str]:
    title = rec.Title or f"[{rec.PublicId}]"
    product = rec.Product_Workload or "Microsoft 365"
    status = rec.Status or "—"
    clouds = rec.Cloud_instance or "General"
    lm = rec.LastModified or "—"
    rel = rec.ReleaseDate or "—"

    summary = (
        f"{product}: **{title}**.\n"
        f"This roadmap item is tracked under PublicId {rec.PublicId}. "
        f"Current status: {status}. Cloud: {clouds}. "
        f"Last modified {lm}; target/release date {rel}."
    )

    changes = (
        "Feature work is progressing based on roadmap telemetry and message center updates. "
        "Naming and scope may evolve as Microsoft ships iterative improvements."
    )

    impact = (
        "Low operational impact for most tenants during initial rollout. "
        "Expect gradual enablement via service-side flighting; timelines depend on ring and cloud. "
        "Admins should validate any policy side-effects in pilot rings."
    )

    actions = (
        "• Communicate the change to affected users/stakeholders.\n"
        "• Validate tenant- or workload-level policies that may influence rollout.\n"
        "• Update training/runbooks once the feature is observed in your tenant.\n"
        "• If applicable, monitor the related Message center post by MessageId."
    )
    return summary, changes, impact, actions


def _ai_sections(args, rec: FeatureRecord) -> Optional[tuple[str, str, str, str]]:
    if not _ai_available(args):
        return None
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
        client = OpenAI()
        prompt = dedent(f"""
        Summarize this Microsoft 365 Roadmap item for an IT admin audience.
        Return four short sections titled exactly:
        Summary, What’s changing, Impact and rollout, Action items.

        PublicId: {rec.PublicId}
        Title: {rec.Title}
        Product/Workload: {rec.Product_Workload}
        Status: {rec.Status}
        Cloud(s): {rec.Cloud_instance}
        Last Modified: {rec.LastModified}
        Release Date: {rec.ReleaseDate}
        Official Link: {rec.Official_Roadmap_link}
        Message Center Id: {rec.MessageId}

        Keep each section 1–3 sentences. Avoid marketing fluff.
        """).strip()

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return None

        sections = {"summary": "", "changes": "", "impact": "", "actions": ""}
        current = None
        for line in text.splitlines():
            l = line.strip()
            key = None
            if l.lower().startswith("summary"):
                key = "summary"
            elif l.lower().startswith("what’s changing") or l.lower().startswith("whats changing") or l.lower().startswith("what's changing"):
                key = "changes"
            elif l.lower().startswith("impact and rollout"):
                key = "impact"
            elif l.lower().startswith("action items"):
                key = "actions"

            if key:
                current = key
                colon = l.find(":")
                if colon >= 0 and colon < len(l) - 1:
                    sections[key] = l[colon + 1 :].strip()
                else:
                    sections[key] = ""
            elif current:
                sections[current] += ("\n" if sections[current] else "") + l

        if not any(sections.values()):
            return None

        return (
            sections.get("summary") or "",
            sections.get("changes") or "",
            sections.get("impact") or "",
            sections.get("actions") or "",
        )
    except Exception:
        return None


# ----------------------------
# CLI
# ----------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="Path to *_master.csv produced by fetch step")
    p.add_argument("--out", required=True, help="Output markdown path")
    p.add_argument("--since")
    p.add_argument("--months")
    p.add_argument("--cloud", action="append", help="Repeatable cloud label filter")
    p.add_argument("--products", help="Comma/pipe separated product/workload filter; blank = all")
    p.add_argument("--forced-ids", help="Comma-separated exact PublicIds to include/order; will synthesize if missing")
    p.add_argument("--ai-off", action="store_true", help="Disable AI deep-dive summaries")
    return p.parse_args()


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    args = _parse_args()

    all_rows = _read_master_csv(args.master)

    # Filter by cloud/products
    rows = _filter_by_cloud(all_rows, args.cloud)
    rows = _filter_by_products(rows, args.products)

    all_rows = _read_master_csv(args.master)
    rows = _filter_by_cloud(all_rows, args.cloud)
    rows = _filter_by_products(rows, args.products)
    print(f"[gen] final row count: {len(rows)}", file=sys.stderr)


    # Forced IDs ordering/synthesis
    forced_ids = _parse_forced_ids(args.forced_ids)
    if forced_ids:
        rows = _apply_forced_ids(rows, forced_ids)

    # Header + body
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = _cloud_display_from_args(args.cloud)

    parts: List[str] = [
        render_header(title=args.title, generated_utc=generated, cloud_display=cloud_display)
    ]
    parts.append(f"\nTotal features: {len(rows)}\n")

    for rec in rows:
        ai = _ai_sections(args, rec)
        if ai is None:
            ai = _rule_based_sections(rec)
        summary, changes, impact, actions = ai
        parts.append(
            render_feature_markdown(
                rec,
                summary=summary,
                changes=changes,
                impact=impact,
                actions=actions,
            )
        )

    md = "\n\n".join(parts).rstrip() + "\n"
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(md)

    print(f"Wrote report: {args.out} (features={len(rows)})")


if __name__ == "__main__":
    main()
