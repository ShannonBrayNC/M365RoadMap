#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Presentation helpers for roadmap report rendering.

This module is intentionally dependency-light and safe to import from
GitHub Actions. Everything here is pure string/Markdown assembly.

Exports:
- CLOUD_LABELS
- render_header(...)
- feature_anchor_id(public_id: str) -> str
- render_feature_markdown(rec: dict, sections: dict | None = None) -> str
"""

from __future__ import annotations

from html import escape
from typing import Mapping, MutableMapping

# Canonical cloud display labels
CLOUD_LABELS: Mapping[str, str] = {
    "Worldwide (Standard Multi-Tenant)": "General",
    "Worldwide": "General",
    "Public": "General",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
}

EMDASH = "—"


def _pill(text: str) -> str:
    """Render a small 'pill' chip using Markdown-compatible inline code style."""
    t = text.strip() or EMDASH
    return f"`{escape(t)}`"


def _safe(v: str | None) -> str:
    return v.strip() if isinstance(v, str) and v.strip() else EMDASH


def feature_anchor_id(public_id: str) -> str:
    """Generate a stable in-page anchor id for ToC links."""
    pid = (public_id or "").strip()
    return f"feature-{pid or 'x'}"


def render_header(
    *,
    title: str,
    generated_utc: str,
    cloud_display: str,
    total: int | None = None,
) -> str:
    """Top-of-report header block."""
    lines: list[str] = []
    lines.append(f"# {escape(title)}")
    sub = f"Generated {escape(generated_utc)} UTC · Cloud filter: {escape(cloud_display or 'All')}"
    lines.append("")
    lines.append(sub)
    if total is not None:
        lines.append("")
        lines.append(f"**Total features:** {total}")
    lines.append("")
    return "\n".join(lines)


def _kv_row(k: str, v: str) -> str:
    return f"| **{escape(k)}** | {escape(v)} |"


def _two_col_row(k1: str, v1: str, k2: str, v2: str) -> str:
    return f"| **{escape(k1)}** | {escape(v1)} | **{escape(k2)}** | {escape(v2)} |"


def render_feature_markdown(
    rec: MutableMapping[str, str],
    *,
    sections: Mapping[str, str] | None = None,
) -> str:
    """
    Render one feature card.

    `rec` is a dict-like with (case-insensitive) keys:
      public_id, title, product_workload, status, last_modified, release_date,
      cloud_instance, source, roadmap_link, message_id, mc_link,
      mc_published, mc_last_updated, mc_services, mc_platforms, mc_tags,
      mc_relevance
    """
    # normalize keys (case-insensitive access)
    def g(*names: str) -> str:
        for n in names:
            for k in rec.keys():
                if k.lower() == n.lower():
                    v = rec[k]
                    return v if isinstance(v, str) else str(v)
        return ""

    public_id = g("public_id")
    title = g("title") or f"[{public_id}]"
    product = g("product_workload")
    status = g("status")
    clouds = g("cloud_instance")
    last_modified = g("last_modified")
    release_date = g("release_date")
    source = g("source")
    roadmap_link = g("roadmap_link") or g("official_roadmap_link")
    message_id = g("message_id")
    mc_link = g("mc_link")

    # Optional MC meta
    mc_relevance = g("mc_relevance")
    mc_services = g("mc_services")
    mc_platforms = g("mc_platforms")
    mc_tags = g("mc_tags")
    mc_published = g("mc_published")
    mc_last_updated = g("mc_last_updated")

    # Title (bold). We keep the Message ID as a hyperlink in the table.
    md: list[str] = []
    md.append(f"### **{escape(title)}**")
    md.append("")

    # Pills row (Status / Release / Clouds) and Products chips row
    pills = f"**Status:** {_pill(_safe(status))} **Release:** {_pill(_safe(release_date))} **Clouds:** {_pill(_safe(clouds))}"
    md.append(pills)
    if product:
        md.append("")
        md.append(_pill(product))
    md.append("")

    # Primary details table (2x4)
    md.append("|  |  |  |  |")
    md.append("|:--|:--|:--|:--|")
    md.append(_two_col_row("Roadmap ID", _safe(public_id), "Product / Workload", _safe(product)))
    md.append(_two_col_row("Status", _safe(status), "Cloud(s)", _safe(clouds)))
    md.append(_two_col_row("Last Modified", _safe(last_modified), "Release Date", _safe(release_date)))
    msg_link = f"[{escape(message_id)}]({escape(mc_link)})" if message_id and mc_link else _safe(message_id)
    md.append(_two_col_row("Source", _safe(source), "Message ID", msg_link))
    md.append("")

    # Optional MC metadata table (appears only if any of these exist)
    if any(x.strip() for x in [mc_relevance, mc_services, mc_platforms, mc_tags, mc_published, mc_last_updated]):
        md.append("<details>")
        md.append("<summary>More from Message Center</summary>")
        md.append("")
        md.append("|  |  |  |  |")
        md.append("|:--|:--|:--|:--|")
        md.append(_two_col_row("Relevance", _safe(mc_relevance), "Services", _safe(mc_services)))
        md.append(_two_col_row("Platforms", _safe(mc_platforms), "Tags", _safe(mc_tags)))
        md.append(_two_col_row("Published", _safe(mc_published), "Last updated", _safe(mc_last_updated)))
        md.append("</details>")
        md.append("")

    # Summary + Sources
    summary = ""
    changes = ""
    impact = ""
    actions = ""
    if sections:
        summary = (sections.get("summary") or "").strip()
        changes = (sections.get("changes") or "").strip()
        impact = (sections.get("impact") or "").strip()
        actions = (sections.get("actions") or "").strip()

    md.append("**Summary**")
    md.append(summary or "*summary pending*")
    # Sources line (Roadmap, Message Center)
    sources_parts: list[str] = []
    if roadmap_link:
        sources_parts.append(f"[Official Roadmap]({escape(roadmap_link)})")
    if mc_link:
        sources_parts.append(f"[Message Center]({escape(mc_link)})")
    if sources_parts:
        md.append("")
        md.append("Sources: " + " | ".join(sources_parts))
    md.append("")

    md.append("**▼ What’s changing**")
    md.append(changes or "*details pending*")
    md.append("")
    md.append("**▼ Impact and rollout**")
    md.append(impact or "*impact pending*")
    md.append("")
    md.append("**▼ Action items**")
    md.append(actions or "*actions pending*")
    md.append("")

    return "\n".join(md)
