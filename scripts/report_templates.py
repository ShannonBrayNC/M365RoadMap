#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# --- Cloud normalization ---

_CLOUD_MAP = {
    "worldwide (standard multi-tenant)": "General",
    "worldwide": "General",
    "general": "General",
    "commercial": "General",
    "gcc": "GCC",
    "gcc high": "GCC High",
    "gcch": "GCC High",
    "dod": "DoD",
}


def normalize_clouds(items: Iterable[str]) -> set[str]:
    """
    Normalize cloud display names to canonical labels.
    Unknown values are preserved as-is (trimmed).
    """
    out: set[str] = set()
    for s in items or []:
        key = (s or "").strip().lower()
        if not key:
            continue
        out.add(_CLOUD_MAP.get(key, s.strip()))
    return out


# --- Data model (matches your CSV columns via generate_report.py mapping) ---

@dataclass
class FeatureRecord:
    public_id: str
    title: str
    source: str
    product_workload: str
    status: str
    last_modified: str
    release_date: str
    cloud_instance: str
    official_roadmap_link: str
    message_id: str

    # Convenience helpers (not serialized)
    @property
    def products_list(self) -> list[str]:
        """
        Split product_workload into pills. Supports '/', ',' separators.
        """
        s = (self.product_workload or "").strip()
        if not s:
            return []
        raw = [p.strip() for part in s.split("/") for p in part.split(",")]
        return [p for p in raw if p]


# --- Rendering helpers ---

def _pill_row(label: str, items: Sequence[str]) -> str:
    if not items:
        return ""
    pills = " ".join(f"`{p}`" for p in items)
    return f"**{label}:** {pills}\n\n"


def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
    """
    Top-of-report header. `cloud_display` is a human string (e.g., 'General' or 'General, GCC').
    """
    return (
        f"# {title}\n"
        f"_Generated {generated_utc}_\n\n"
        f"**Cloud filter:** {cloud_display}\n\n"
    )


def render_feature_markdown(rec: FeatureRecord) -> str:
    """
    Pretty per-feature section.
    - Bold title
    - Hyperlink Message Center ID (when present)
    - Status, Release Date, Clouds
    - Products tag pills
    - Summary placeholder blocks
    """
    # Title line: [ID] Title (bold)
    id_bracket = f"[{rec.public_id}]" if rec.public_id else "[—]"
    title_line = f"**{id_bracket} {rec.title or '(No title)'}**"

    # Facts line
    clouds = (rec.cloud_instance or "—").strip() or "—"
    status = (rec.status or "—").strip() or "—"
    last_mod = (rec.last_modified or "—").strip() or "—"
    rel = (rec.release_date or "—").strip() or "—"

    # Links: Message Center (ID hyperlink) and Roadmap link
    mc_part = ""
    if rec.message_id:
        mc_url = f"https://admin.microsoft.com/Adminportal/Home#/messagecenter/:/messages/{rec.message_id}"
        mc_part = f" • Message Center: [{rec.message_id}]({mc_url})"
    rm_part = ""
    if rec.official_roadmap_link:
        rm_part = f" • [Official Roadmap]({rec.official_roadmap_link})"

    facts = (
        f"Product/Workload: {(rec.product_workload or '—')}"
        f" • Status: {status}"
        f" • Cloud(s): {clouds}"
        f" • Last Modified: {last_mod}"
        f" • Release Date: {rel}"
        f" • Source: {(rec.source or '—')}"
        f"{mc_part}{rm_part}"
    )

    # Products tag pills
    pills = _pill_row("Products", rec.products_list)

    # AI placeholders / content blocks
    body = (
        f"{title_line}\n\n"
        f"{facts}\n\n"
        f"{pills}"
        f"**Summary**  \n"
        f"(summary pending)\n\n"
        f"**What’s changing**  \n"
        f"(details pending)\n\n"
        f"**Impact and rollout**  \n"
        f"(impact pending)\n\n"
        f"**Action items**  \n"
        f"(actions pending)\n\n"
    )
    return body


def render_toc(features: list[FeatureRecord]) -> str:
    """
    Mini table of contents with anchors by public_id (falls back to slugified title).
    """
    if not features:
        return ""
    lines = ["## Table of Contents"]
    for rec in features:
        anchor = rec.public_id or (rec.title.lower().strip().replace(" ", "-") if rec.title else "item")
        label = f"[{rec.public_id}] {rec.title}" if rec.public_id else (rec.title or "(No title)")
        lines.append(f"- [{label}](#{anchor})")
    return "\n".join(lines) + "\n\n"
