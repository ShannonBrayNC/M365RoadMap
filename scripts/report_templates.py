#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# ---------------------------------------------------------------------
# Cloud constants and normalization
# ---------------------------------------------------------------------

# Canonical cloud keys -> display labels
CLOUD_LABELS: dict[str, str] = {
    "General": "Worldwide (Standard Multi-Tenant)",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
}

# Normalize many inputs to the canonical keys above
_CLOUD_NORMALIZE_MAP: dict[str, str] = {
    # General / Worldwide
    "general": "General",
    "worldwide": "General",
    "worldwide (standard multi-tenant)": "General",
    "ww": "General",
    "public": "General",
    # GCC
    "gcc": "GCC",
    "government community cloud": "GCC",
    # GCC High
    "gcch": "GCC High",
    "gcc high": "GCC High",
    # DoD
    "dod": "DoD",
    "department of defense": "DoD",
}

def normalize_clouds(values: Sequence[str] | str) -> set[str]:
    """
    Accepts a single string (possibly comma/pipe separated) or a list/tuple.
    Returns a set of canonical cloud keys: {'General','GCC','GCC High','DoD'}.
    Unrecognized inputs are returned as-is (title-cased) so nothing is lost.
    """
    items: list[str] = []
    if isinstance(values, str):
        parts = [p.strip() for p in values.replace("|", ",").split(",")]
        items = [p for p in parts if p]
    else:
        items = [str(v).strip() for v in values if str(v).strip()]

    canon: set[str] = set()
    for raw in items:
        key = _CLOUD_NORMALIZE_MAP.get(raw.lower())
        if key:
            canon.add(key)
        else:
            canon.add(raw.title())
    return canon


# ---------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class FeatureRecord:
    """
    Canonical feature row used by generate_report.py and friends.
    Field names use snake_case to avoid CSV header ambiguity.
    """
    public_id: str
    title: str
    source: str
    product: str
    status: str
    last_modified: str
    release_date: str
    clouds: str          # display text as stored in CSV (e.g., "General; GCC")
    roadmap_link: str    # https://www.microsoft.com/microsoft-365/roadmap?...searchterms=<id>
    message_id: str      # e.g., "MC1048620"


# ---------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------

def message_center_url(message_id: str) -> str | None:
    """
    Build the Microsoft 365 admin message center URL for an MC id.
    """
    mid = (message_id or "").strip()
    if not mid:
        return None
    # Admin center accepts this pattern reliably:
    return f"https://admin.microsoft.com/?ref=MessageCenter&id={mid}"


# ---------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------

def _fmt(text: str | None) -> str:
    return (text or "").strip() or "—"

def _split_csvish(value: str | None) -> list[str]:
    """
    Split a product or cloud cell (commas, pipes, slashes, semicolons supported).
    """
    if not value:
        return []
    raw = value.replace("|", ",").replace(";", ",").replace("/", ",")
    return [p.strip() for p in raw.split(",") if p.strip()]

def _slug(s: str) -> str:
    """
    Very small slug that works well for GitHub Markdown heading anchors.
    """
    keep = []
    s = s.lower()
    for ch in s:
        if ch.isalnum() or ch in ("-", " "):
            keep.append(ch)
    return "-".join("".join(keep).split())

def _pill_row(label: str, items: list[str]) -> str:
    """
    Render a label + "pills" using inline code as the simplest Markdown stand-in.
    """
    if not items:
        return ""
    pills = " ".join(f"`{i}`" for i in items)
    return f"**{label}:** {pills}\n"

def _detail_table(rows: list[tuple[str, str]]) -> str:
    """
    Render a 2-column Markdown table of key/value pairs.
    """
    if not rows:
        return ""
    header = "| Field | Value |\n|---|---|\n"
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return header + body + "\n"

def _sources_line(roadmap_link: str, message_id: str) -> str:
    links: list[str] = []
    if message_id.strip():
        murl = message_center_url(message_id)
        if murl:
            links.append(f"[Message center {message_id}]({murl})")
    if roadmap_link.strip():
        links.append(f"[Roadmap #{_fmt(None) if not roadmap_link else 'link'}]({roadmap_link})")
    if not links:
        return ""
    return f"**Sources:** " + ", ".join(links) + "\n"


# ---------------------------------------------------------------------
# Header, TOC, and global UI pieces
# ---------------------------------------------------------------------

def render_header(
    *,
    title: str,
    generated_utc: str,
    cloud_display: str,
    total_features: int,
    products: list[str] | None = None,
) -> str:
    """
    Report header block with optional product pill row and a divider.
    """
    lines = [
        f"# {title}",
        f"Generated {generated_utc}",
        "",
        f"**{title}** &nbsp;&nbsp; _Generated {generated_utc}_ &nbsp;&nbsp; **Cloud filter:** {cloud_display}",
        "",
        f"**Total features:** {total_features}",
    ]
    if products:
        lines.append(_pill_row("Products", products).rstrip())
    lines += ["", "---", ""]
    return "\n".join(lines)

def render_toc(features: Sequence[FeatureRecord]) -> str:
    """
    Mini table of contents linking to each feature's anchor.
    """
    if not features:
        return ""
    items = []
    for f in features:
        rid = f.public_id or "id"
        title = f.title or f"[{rid}]"
        anchor = f"rid-{rid}"
        items.append(f"- [{title}](#${anchor})")
    # Some Markdown renderers don't like the "$" in anchors; we add both forms.
    toc = ["## Table of contents", ""]
    toc.extend(items)
    toc.extend(["", "---", ""])
    # Replace #$anchor with #anchor for renderers that prefer the simpler form
    return "\n".join(toc).replace("(#$", "(#")


# ---------------------------------------------------------------------
# Feature rendering (pretty card)
# ---------------------------------------------------------------------

def render_feature_card(feature: FeatureRecord) -> str:
    """
    Pretty, compact feature "card" in Markdown:
      - Bold title with hyperlink to the roadmap (when available)
      - Status, Release date, Clouds, Product in a small details table
      - Products shown again as pill row (nice visual scan)
      - Sources line including Message Center link (if message_id present)
      - Placeholder AI sections (kept for downstream PPT use)
    """
    rid = feature.public_id or "—"
    # Title and primary link
    title_txt = feature.title or f"[{rid}]"
    title_md = f"**{title_txt}**"
    if feature.roadmap_link.strip():
        title_md = f"**[{title_txt}]({feature.roadmap_link})**"

    # Stable anchor for TOC
    anchor = f"rid-{rid}"

    # Clouds: display raw cell, but also normalize a readable list for pills
    clouds_disp = _fmt(feature.clouds)
    clouds_norm = sorted(normalize_clouds(_split_csvish(feature.clouds))) if feature.clouds else []
    clouds_pills = [CLOUD_LABELS.get(c, c) for c in clouds_norm] if clouds_norm else []

    # Products: pills derived from product cell
    prod_items = _split_csvish(feature.product)
    prod_pills = prod_items

    # Details table
    details = _detail_table(
        [
            ("Status", _fmt(feature.status)),
            ("Release date", _fmt(feature.release_date)),
            ("Clouds", clouds_disp if clouds_disp != "—" else "—"),
            ("Product / Workload", _fmt(feature.product)),
            ("Source", _fmt(feature.source)),
            ("Message ID", f"[{feature.message_id}]({message_center_url(feature.message_id)})" if feature.message_id else "—"),
        ]
    )

    # Sources line
    srcs = _sources_line(feature.roadmap_link, feature.message_id)

    # Assemble card
    parts: list[str] = [
        f"### <a id=\"{anchor}\"></a> {title_md}",
        "",
        details,
    ]

    # Pills rows
    if prod_pills:
        parts.append(_pill_row("Products", prod_pills))
    if clouds_pills:
        parts.append(_pill_row("Clouds", clouds_pills))

    if srcs:
        parts += ["", srcs]

    # Placeholder AI sections the caller can overwrite later if desired
    parts += [
        "",
        "**Summary**  \n(summary pending)",
        "",
        "**What’s changing**  \n(details pending)",
        "",
        "**Impact and rollout**  \n(impact pending)",
        "",
        "**Action items**  \n(actions pending)",
        "",
        "---",
        "",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------
# Simple legacy block (kept for compatibility with older tests)
# ---------------------------------------------------------------------

def render_feature_markdown(feature: FeatureRecord) -> str:
    rid = feature.public_id or "—"
    title = feature.title or f"[{rid}]"
    title_md = f"**{title}**"
    if feature.roadmap_link.strip():
        title_md = f"**[{title}]({feature.roadmap_link})**"
    parts = [
        f"### {title_md}",
        "",
        f"- **Roadmap ID:** {rid}",
        f"- **Product / Workload:** {_fmt(feature.product)}",
        f"- **Status:** {_fmt(feature.status)}",
        f"- **Last Modified:** {_fmt(feature.last_modified)}",
        f"- **Release Date:** {_fmt(feature.release_date)}",
        f"- **Clouds:** {_fmt(feature.clouds)}",
        f"- **Source:** {_fmt(feature.source)}",
    ]
    if feature.message_id:
        parts.append(f"- **Message ID:** [{feature.message_id}]({message_center_url(feature.message_id)})")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

__all__ = [
    "CLOUD_LABELS",
    "normalize_clouds",
    "FeatureRecord",
    "render_header",
    "render_toc",
    "render_feature_card",
    "render_feature_markdown",
    "message_center_url",
]
