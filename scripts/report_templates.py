#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Markdown UI helpers for the roadmap report.

Provides:
- CLOUD_LABELS
- normalize_clouds(values)
- render_header(title, generated_utc, cloud_display)
- render_products_row(products)
- render_toc(features)
- render_feature_section(feature)
"""

from __future__ import annotations

from typing import Iterable, Sequence

# Canonical cloud display labels we want to show in the report
CLOUD_LABELS: dict[str, str] = {
    "Worldwide (Standard Multi-Tenant)": "General",
    "General": "General",
    "GCC": "GCC",
    "GCC High": "GCCH",
    "GCCH": "GCCH",
    "DoD": "DoD",
    "DOD": "DoD",
}

# Common synonyms → canonical
_CLOUD_SYNONYMS: dict[str, str] = {
    "worldwide": "General",
    "standard multi-tenant": "General",
    "multi-tenant": "General",
    "general": "General",
    "gcc": "GCC",
    "gcc high": "GCCH",
    "gcch": "GCCH",
    "dod": "DoD",
    "usgov": "GCCH",
    "us gov high": "GCCH",
    "us gov dod": "DoD",
}


def normalize_clouds(values: Iterable[str] | str | None) -> set[str]:
    """
    Returns a set of canonical cloud labels (General/GCC/GCCH/DoD) from arbitrary inputs.
    If values is None or empty → empty set (caller decides default behavior).
    """
    if values is None:
        return set()

    if isinstance(values, str):
        raw = [values]
    else:
        raw = list(values)

    out: set[str] = set()
    for v in raw:
        v = (v or "").strip()
        if not v:
            continue
        # try direct map
        if v in CLOUD_LABELS:
            out.add(CLOUD_LABELS[v])
            continue
        # try synonym
        key = v.lower()
        if key in _CLOUD_SYNONYMS:
            out.add(_CLOUD_SYNONYMS[key])
            continue
        # pass-through last resort: title-case short labels
        if key in ("general", "gcc", "gcch", "dod"):
            out.add(key.upper() if key != "general" else "General")
    return out


def _h1(text: str) -> str:
    return f"# {text}\n"


def _hr() -> str:
    return "\n---\n"


def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
    """
    Top header block. Example:

    # Roadmap Report
    Generated 2025-08-16 09:50 UTC

    **Cloud filter:** General
    """
    lines = [
        _h1(title).rstrip(),
        f"Generated {generated_utc}",
        "",
        f"**Cloud filter:** {cloud_display or 'All'}",
        "",
    ]
    return "\n".join(lines)


def render_products_row(products: Sequence[str]) -> str:
    """
    Render a small 'Products' pills row: backtick-wrapped tokens.
    """
    tokens = [p.strip() for p in products if p.strip()]
    if not tokens:
        return ""
    pills = " ".join(f"`{p}`" for p in tokens)
    return f"**Products:** {pills}\n"


def _slugify(s: str) -> str:
    keep = []
    for ch in s:
        if ch.isalnum():
            keep.append(ch.lower())
        elif ch in (" ", "-", "_"):
            keep.append("-")
    slug = "".join(keep).strip("-")
    return "-".join([seg for seg in slug.split("-") if seg])


def render_toc(features: Sequence[dict]) -> str:
    """
    Minimal bulleted Table of Contents linking to anchors by PublicId + Title.
    """
    if not features:
        return ""
    lines = ["**Contents**", ""]
    for r in features:
        pid = str(r.get("PublicId", "") or "").strip()
        title = (r.get("Title") or f"[{pid}]").strip()
        anchor = f"feature-{_slugify(f'{pid}-{title}')}"
        lines.append(f"- [{pid} – {title}](#{anchor})")
    lines.append("")
    return "\n".join(lines)


def render_feature_section(r: dict) -> str:
    """
    A single feature 'card' section:
      ### [89975] Title
      **Status:** X  •  **Release:** Y  •  **Clouds:** A, B
      Source: [Message center MC123456](https://admin.microsoft.com/Adminportal/Home#/messagecenter?id=MC123456)
      [Official roadmap](https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms=89975)

      **Summary**
      (summary pending)
      ...
    """
    pid = str(r.get("PublicId", "") or "").strip()
    title = (r.get("Title") or f"[{pid}]").strip()
    status = (r.get("Status") or "—").strip()
    release = (r.get("ReleaseDate") or "—").strip()
    clouds_raw = (r.get("Cloud_instance") or "").strip()

    clouds_canon = sorted(normalize_clouds([c.strip() for c in clouds_raw.split(",") if c.strip()])) or ["—"]
    clouds_display = ", ".join(clouds_canon)

    roadmap_url = (r.get("Official_Roadmap_link") or "").strip()
    message_id = (r.get("MessageId") or "").strip()

    # Anchor
    anchor = f"feature-{_slugify(f'{pid}-{title}')}"
    head = f"### <a id=\"{anchor}\"></a> [{pid}] **{title}**\n"

    meta_parts = [f"**Status:** {status}", f"**Release:** {release}", f"**Clouds:** {clouds_display}"]
    meta = "  •  ".join(meta_parts)

    # Source lines
    lines = [head, meta]
    if message_id:
        mc_link = f"https://admin.microsoft.com/Adminportal/Home#/messagecenter?id={message_id}"
        lines.append(f"Source: [Message center {message_id}]({mc_link})")
    if roadmap_url:
        lines.append(f"[Official roadmap]({roadmap_url})")

    # AI placeholder blocks (kept minimal so you can swap in later)
    lines.append("")
    lines.append("**Summary**")
    lines.append("(summary pending)")
    lines.append("")
    lines.append("**What’s changing**")
    lines.append("(details pending)")
    lines.append("")
    lines.append("**Impact and rollout**")
    lines.append("(impact pending)")
    lines.append("")
    lines.append("**Action items**")
    lines.append("(actions pending)")
    lines.append("")
    return "\n".join(lines)
