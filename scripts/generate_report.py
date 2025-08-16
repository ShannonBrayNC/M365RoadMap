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

# We rely on your shared templates/utilities
# FeatureRecord is the row model; render_header and render_feature_markdown produce MD
from report_templates import FeatureRecord, render_feature_markdown, render_header  # type: ignore[import-not-found]


# ----------------------------
# CSV I/O
# ----------------------------

CSV_HEADERS = [
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


def _read_master_csv(path: str) -> List[FeatureRecord]:
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


def _filter_by_cloud(rows: Sequence[FeatureRecord], selected_clouds: Optional[Sequence[str]]) -> List[FeatureRecord]:
    if not selected_clouds:
        return list(rows)
    selected = set([c.strip() for c in selected_clouds if c and c.strip()])
    if not selected:
        return list(rows)
    out: List[FeatureRecord] = []
    for r in rows:
        c = (r.Cloud_instance or "").strip()
        if not c:
            # keep untagged items if Worldwide/General is in the filter
            if "Worldwide (Standard Multi-Tenant)" in selected:
                out.append(r)
        elif c in selected:
            out.append(r)
    return out


def _parse_products_arg(products: Optional[str]) -> List[str]:
    """
    Accept comma or pipe delimited. Blank → [] (means 'all').
    """
    if not products:
        return []
    raw = [t.strip() for t in products.replace("|", ",").split(",")]
    return [t for t in raw if t]


def _filter_by_products(rows: Sequence[FeatureRecord], products: Optional[str]) -> List[FeatureRecord]:
    tokens = _parse_products_arg(products)
    if not tokens:
        return list(rows)
    toks = [t.lower() for t in tokens]
    out: List[FeatureRecord] = []
    for r in rows:
        val = (r.Product_Workload or "").lower()
        # include if any token is a substring of the Product_Workload
        if any(t in val for t in toks):
            out.append(r)
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
