#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate a Markdown roadmap report from a master CSV emitted by the fetch step.

Highlights:
- Mini table of contents
- Product "pill" chips
- Status / Release / Clouds pill row
- Message ID hyperlinked to the Message Center admin portal
- Pulls Message Center body (when present in CSV as MC_Body / MessageBody / Body)
  and heuristically maps it into Summary / What’s changing / Impact / Actions.
- Gracefully degrades to placeholders if MC fields are missing.

Expected CSV columns (case-insensitive; best effort):
  PublicId, Title, Source, Product_Workload, Status, LastModified, ReleaseDate,
  Cloud_instance, Official_Roadmap_link, MessageId,
  [optional MC_* columns]: MC_Body/MessageBody/Body, MC_Published, MC_LastUpdated,
  MC_Services, MC_Platforms, MC_Tags, MC_Relevance

Usage:
  python scripts/generate_report.py --title X --master output/..._master.csv --out output/X.md \
    [--since YYYY-MM-DD] [--months N] [--cloud "Worldwide (Standard Multi-Tenant)" ...] \
    [--products "Teams|SharePoint"] [--forced-ids "497910,4710"]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from bs4 import BeautifulSoup  # installed in CI
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

# Local helpers for rendering
from scripts.report_templates import (
    CLOUD_LABELS,
    feature_anchor_id,
    render_feature_markdown,
    render_header,
)

EMDASH = "—"


# ---------- Models & CSV utilities ----------


@dataclass
class FeatureRecord:
    public_id: str = ""
    title: str = ""
    source: str = ""
    product_workload: str = ""
    status: str = ""
    last_modified: str = ""
    release_date: str = ""
    cloud_instance: str = ""
    roadmap_link: str = ""
    message_id: str = ""

    # Optional (Message Center enrichment)
    mc_body: str = ""
    mc_published: str = ""
    mc_last_updated: str = ""
    mc_services: str = ""
    mc_platforms: str = ""
    mc_tags: str = ""
    mc_relevance: str = ""

    @property
    def mc_link(self) -> str:
        mid = (self.message_id or "").strip()
        if not mid:
            return ""
        # This is the standard admin portal deep link
        return f"https://admin.microsoft.com/adminportal/home#/MessageCenter/:/messages/{mid}"


def _first(row: dict[str, str], *names: str) -> str:
    """Case-insensitive getter for any of the provided column names."""
    if not row:
        return ""
    low = {k.lower(): v for k, v in row.items()}
    for n in names:
        v = low.get(n.lower())
        if v is not None:
            return v
    return ""


def _read_master_csv(path: str | Path) -> list[FeatureRecord]:
    records: list[FeatureRecord] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rec = FeatureRecord(
                public_id=_first(r, "PublicId", "public_id", "RoadmapId", "id"),
                title=_first(r, "Title", "title"),
                source=_first(r, "Source", "source"),
                product_workload=_first(r, "Product_Workload", "Product", "Workload", "product_workload"),
                status=_first(r, "Status", "status"),
                last_modified=_first(r, "LastModified", "last_modified", "LastModifiedDate"),
                release_date=_first(r, "ReleaseDate", "release_date"),
                cloud_instance=_first(r, "Cloud_instance", "Cloud", "Clouds", "cloud_instance"),
                roadmap_link=_first(r, "Official_Roadmap_link", "Roadmap", "roadmap_link"),
                message_id=_first(r, "MessageId", "message_id", "MC_MessageId"),
                mc_body=_first(r, "MC_Body", "MessageBody", "Body", "mc_body"),
                mc_published=_first(r, "MC_Published", "mc_published", "Published"),
                mc_last_updated=_first(r, "MC_LastUpdated", "mc_last_updated", "LastUpdated"),
                mc_services=_first(r, "MC_Services", "mc_services", "Services", "Service"),
                mc_platforms=_first(r, "MC_Platforms", "mc_platforms", "Platforms", "Platform"),
                mc_tags=_first(r, "MC_Tags", "mc_tags", "Tags"),
                mc_relevance=_first(r, "MC_Relevance", "mc_relevance", "Relevance", "Severity"),
            )
            # Fill missing title with bracketed id (keeps headings non-empty)
            if not rec.title and rec.public_id:
                rec.title = f"[{rec.public_id}]"
            # Fill roadmap link if missing
            if not rec.roadmap_link and rec.public_id:
                rec.roadmap_link = (
                    "https://www.microsoft.com/microsoft-365/roadmap"
                    f"?filters=&searchterms={rec.public_id}"
                )
            records.append(rec)
    return records


# ---------- Filters & helpers ----------


def normalize_clouds(values: Iterable[str]) -> set[str]:
    """
    Normalize a list of cloud labels into our canonical display set.
    Unrecognized entries are ignored.
    """
    canon: set[str] = set()
    for v in values:
        key = (v or "").strip()
        if not key:
            continue
        # exact
        if key in CLOUD_LABELS:
            canon.add(CLOUD_LABELS[key])
            continue
        # case-insensitive lookup
        for raw, disp in CLOUD_LABELS.items():
            if raw.lower() == key.lower():
                canon.add(disp)
                break
    return canon


def _display_cloud_list(sel: Sequence[str] | None) -> str:
    if not sel:
        return "All"
    disp = [CLOUD_LABELS.get(s, s) for s in sel]
    uniq = []
    for d in disp:
        if d not in uniq:
            uniq.append(d)
    return ", ".join(uniq)


def filter_by_cloud(rows: list[FeatureRecord], selected: Sequence[str] | None) -> list[FeatureRecord]:
    """
    Keep rows whose cloud(s) intersect the selected set.
    If selected is None or empty, return all.
    """
    if not selected:
        return rows
    want = set(_display_cloud_list(selected).split(", "))
    out: list[FeatureRecord] = []
    for r in rows:
        have = normalize_clouds([(r.cloud_instance or "").strip()] if r.cloud_instance else [])
        # If row doesn't list clouds, include it by default
        if not have or have & want:
            out.append(r)
    return out


def filter_by_products(rows: list[FeatureRecord], products_raw: str) -> list[FeatureRecord]:
    """Filter by comma/pipe-separated substring matches on `product_workload` (case-insensitive)."""
    if not products_raw or not products_raw.strip():
        return rows
    terms = [t.strip().lower() for t in re.split(r"[|,]", products_raw) if t.strip()]
    if not terms:
        return rows
    out: list[FeatureRecord] = []
    for r in rows:
        hay = (r.product_workload or "").lower()
        if any(t in hay for t in terms):
            out.append(r)
    return out


def _anchor_link(title: str, public_id: str) -> str:
    aid = feature_anchor_id(public_id)
    safe_title = html.escape(title or f"[{public_id}]")
    return f"- [{safe_title}](#{aid})"


def _best_body_text(html_or_text: str) -> str:
    """Return plain text from HTML or pass-through clean text."""
    if not html_or_text:
        return ""
    s = html_or_text
    if "<" in s and ">" in s and BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(s, "html.parser")
            # keep line breaks for p/li
            for br in soup.find_all(["br"]):
                br.replace_with("\n")
            for p in soup.find_all(["p", "li", "h1", "h2", "h3"]):
                if p.text and not p.text.endswith("\n"):
                    p.append("\n")
            s = soup.get_text(separator="").strip()
        except Exception:
            pass
    # basic cleanup
    s = re.sub(r"\r\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _split_mc_sections(text: str) -> dict[str, str]:
    """
    Heuristically split Message Center body into sections:
    summary / changes / impact / actions
    using common headings seen in MC posts.
    """
    clean = _best_body_text(text)
    if not clean:
        return {"summary": "", "changes": "", "impact": "", "actions": ""}

    # Lowercased copy for searches but preserve original lines for output chunks
    lines = clean.splitlines()
    lower = [ln.lower().strip() for ln in lines]

    # Find heading indices
    def idx_of(*alts: str) -> int | None:
        for i, l in enumerate(lower):
            if any(l.startswith(a) for a in alts):
                return i
        return None

    i_summary = 0
    i_when = idx_of("when this will happen")
    i_affect = idx_of("how this will affect your organization", "how will this affect your organization")
    i_prepare = idx_of("what you need to do to prepare", "what you can do to prepare")

    def slice_text(start: int | None, end: int | None) -> str:
        if start is None:
            return ""
        j = end if end is not None else len(lines)
        chunk = "\n".join(lines[start:j]).strip()
        # remove the heading line if present
        return "\n".join(chunk.splitlines()[1:]).strip() if chunk else ""

    # Compose sections
    summary = "\n".join(lines[i_summary : (i_when or i_affect or i_prepare or len(lines))]).strip()
    changes = slice_text(i_when, i_affect or i_prepare)
    impact = slice_text(i_affect, i_prepare)
    actions = slice_text(i_prepare, None)

    return {
        "summary": summary,
        "changes": changes,
        "impact": impact,
        "actions": actions,
    }


# ---------- CLI & render ----------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate roadmap markdown report.")
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="Path to master CSV from fetch step")
    p.add_argument("--out", required=True, help="Output markdown path")
    p.add_argument("--since", default="")
    p.add_argument("--months", default="")
    p.add_argument("--cloud", action="append", default=[], help="Cloud display, e.g. 'Worldwide (Standard Multi-Tenant)' or 'GCC'")
    p.add_argument("--products", default="", help="Comma/pipe separated substring filter on Product/Workload")
    p.add_argument("--forced-ids", default="", help="Comma-separated PublicIds to force/include in this order")
    return p.parse_args(argv)


def _parse_forced_ids(s: str) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in re.split(r"[,\s]+", s) if x.strip()]


def _synthetic_row(public_id: str) -> FeatureRecord:
    return FeatureRecord(
        public_id=public_id,
        title=f"[{public_id}]",
        roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}",
        source="seed",
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    rows = _read_master_csv(args.master)
    # Cloud & product filtering
    rows = filter_by_cloud(rows, args.cloud)
    rows = filter_by_products(rows, args.products)

    # Forced IDs: ensure inclusion and exact ordering first, then append the rest
    forced = _parse_forced_ids(args.forced_ids)
    if forced:
        # map by id for quick lookup
        by_id = {r.public_id: r for r in rows if r.public_id}
        ordered: list[FeatureRecord] = []
        for fid in forced:
            ordered.append(by_id.get(fid) or _synthetic_row(fid))
        # append others not already included
        seen = {r.public_id for r in ordered if r.public_id}
        ordered.extend([r for r in rows if r.public_id not in seen])
        rows = ordered

    total = len(rows)
    cloud_display = _display_cloud_list(args.cloud)
    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    # Header + mini ToC
    parts: list[str] = []
    parts.append(
        render_header(
            title=args.title,
            generated_utc=generated,
            cloud_display=cloud_display,
            total=total,
        )
    )

    # ToC (short list of links to each feature)
    if rows:
        parts.append("**Contents**")
        parts.append("")
        for r in rows:
            parts.append(_anchor_link(r.title or f"[{r.public_id}]", r.public_id))
        parts.append("")

    # Features
    for r in rows:
        # derive MC sections from any body column
        sections = _split_mc_sections(r.mc_body) if r.mc_body else {"summary": "", "changes": "", "impact": "", "actions": ""}

        # Prepare a dict for the renderer (it expects dict-like)
        rec_map = {
            "public_id": r.public_id,
            "title": r.title,
            "product_workload": r.product_workload,
            "status": r.status,
            "cloud_instance": r.cloud_instance,
            "last_modified": r.last_modified,
            "release_date": r.release_date,
            "source": r.source,
            "roadmap_link": r.roadmap_link,
            "message_id": r.message_id,
            "mc_link": r.mc_link,
            "mc_relevance": r.mc_relevance,
            "mc_services": r.mc_services,
            "mc_platforms": r.mc_platforms,
            "mc_tags": r.mc_tags,
            "mc_published": r.mc_published,
            "mc_last_updated": r.mc_last_updated,
        }

        # Anchor anchor
        parts.append(f'<a id="{feature_anchor_id(r.public_id)}"></a>')
        parts.append(render_feature_markdown(rec_map, sections=sections))
        parts.append("---")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"[gen] wrote: {out_path} (features={total})")


if __name__ == "__main__":
    main()
