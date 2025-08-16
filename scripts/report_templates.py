#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Lightweight helpers shared by report-generation and fetch scripts.

Exports:
- CLOUD_LABELS: mapping of canonical short names -> human display labels
- normalize_clouds(value): normalize any cloud inputs into a set[str] of canonical short names
- parse_date_soft(text): best-effort date normalization -> 'YYYY-MM-DD' (or original text on failure)
- FeatureRecord: dataclass describing a roadmap feature for rendering
- render_header(...): header for the report (supports cloud_display and legacy cloud_label)
- render_feature_markdown(feature): pretty, single-section markdown for a feature
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence, Set, Union
import re

# ---------------------------------------------------------------------------
# Cloud constants / normalization
# ---------------------------------------------------------------------------

# Canonical short -> human display
CLOUD_LABELS: dict[str, str] = {
    "General": "Worldwide (Standard Multi-Tenant)",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
}

# Flexible aliases (lowercased) -> canonical short
_CLOUD_ALIASES: dict[str, str] = {
    "worldwide (standard multi-tenant)": "General",
    "worldwide": "General",
    "general": "General",
    "public": "General",
    "commercial": "General",
    "gcc": "GCC",
    "g.c.c.": "GCC",
    "gcc high": "GCC High",
    "gcch": "GCC High",
    "gcc-high": "GCC High",
    "dod": "DoD",
    "do d": "DoD",
    "dept of defense": "DoD",
    "department of defense": "DoD",
}

def _to_iter(value: Union[str, Sequence[str], None]) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return value

def normalize_clouds(value: Union[str, Sequence[str], None]) -> Set[str]:
    """
    Normalize arbitrary cloud strings into a set of canonical short names:
    {'General', 'GCC', 'GCC High', 'DoD'}

    Accepts single string or any sequence of strings. Returns an empty set if no match.
    """
    out: Set[str] = set()
    for raw in _to_iter(value):
        s = str(raw).strip()
        if not s:
            continue
        key = s.lower()
        canon = _CLOUD_ALIASES.get(key)
        if canon:
            out.add(canon)
            continue
        # try loose contains for the long label -> 'General'
        if "worldwide" in key and "tenant" in key:
            out.add("General")
            continue
        # fall back: if exact matches canonical short names
        if s in CLOUD_LABELS:
            out.add(s)
    return out

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# Accept a few loose formats commonly seen in feeds or CSV
_DATE_PATTERNS: list[str] = [
    r"^\d{4}-\d{2}-\d{2}$",          # 2025-08-16
    r"^\d{4}/\d{2}/\d{2}$",          # 2025/08/16
    r"^\d{2}/\d{2}/\d{4}$",          # 08/16/2025
    r"^[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}$",  # Aug 16, 2025  / August 16, 2025
]

def _try_parse_date(text: str) -> Optional[datetime]:
    t = text.strip()
    if not t:
        return None
    # ISO first
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass
    # Month name
    try:
        return datetime.strptime(t, "%b %d, %Y")
    except ValueError:
        pass
    try:
        return datetime.strptime(t, "%B %d, %Y")
    except ValueError:
        pass
    # If it's just YYYY-MM, coerce to first of month
    m = re.match(r"^(\d{4})-(\d{2})$", t)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)}-{m.group(2)}-01", "%Y-%m-%d")
        except ValueError:
            return None
    return None

def parse_date_soft(text: Optional[str]) -> str:
    """
    Best effort: normalize to YYYY-MM-DD.
    Returns empty string on None/empty; returns original text if parsing fails.
    """
    if not text:
        return ""
    dt = _try_parse_date(text)
    return dt.strftime("%Y-%m-%d") if dt else text

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

@dataclass
class FeatureRecord:
    public_id: str
    title: str
    product: str | None = ""
    status: str | None = ""
    clouds: Sequence[str] | None = None  # canonical shorts preferred
    last_modified: str | None = ""
    release_date: str | None = ""
    source: str = ""
    message_id: str | None = ""
    roadmap_link: str | None = ""

def render_header(
    title: str,
    generated_utc: str,
    cloud_display: Optional[str] = None,
    **kwargs,
) -> str:
    """
    Render the report header.

    Preferred arg: `cloud_display`.
    Back-compat: accepts legacy `cloud_label` via kwargs if `cloud_display` is not provided.
    """
    if cloud_display is None:
        cloud_display = kwargs.pop("cloud_label", None) or "General"
    header = []
    header.append("Roadmap Report")
    header.append(f"Generated {generated_utc}")
    header.append("")  # blank line
    header.append(f"{title} Generated {generated_utc} Cloud filter: {cloud_display}")
    header.append("")  # trailing blank line
    return "\n".join(header)

def _fallback(v: Optional[str], dash: str = "—") -> str:
    v = (v or "").strip()
    return v if v else dash

def _clouds_display(shorts: Sequence[str] | None) -> str:
    if not shorts:
        return "—"
    # Map canonical shorts to labels for display; if unknown, show as-is
    labels = [CLOUD_LABELS.get(s, s) for s in shorts]
    # For compactness show canonical short if you prefer:
    # labels = list(shorts)
    return ", ".join(labels)

def render_feature_markdown(f: FeatureRecord) -> str:
    """
    Returns a markdown block for a single feature with placeholder sections.
    """
    pid = _fallback(f.public_id)
    title = _fallback(f.title, dash=f"[{pid}]")
    product = _fallback(f.product)
    status = _fallback(f.status)
    clouds_disp = _clouds_display(f.clouds)
    last_mod = _fallback(parse_date_soft(f.last_modified))
    rel = _fallback(parse_date_soft(f.release_date))
    source = _fallback(f.source)
    msgid = _fallback(f.message_id)
    rmlink = f.roadmap_link or (f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pid}" if pid and pid != "—" else "")

    lines: list[str] = []
    lines.append(
        f"[{pid}] {title} "
        f"Product/Workload: {product} "
        f"Status: {status} "
        f"Cloud(s): {clouds_disp} "
        f"Last Modified: {last_mod} "
        f"Release Date: {rel} "
        f"Source: {source} "
        f"Message ID: {msgid} "
        f"Official Roadmap: {rmlink}".rstrip()
    )
    lines.append("")  # blank
    lines.append("Summary (summary pending)")
    lines.append("")
    lines.append("What’s changing (details pending)")
    lines.append("")
    lines.append("Impact and rollout (impact pending)")
    lines.append("")
    lines.append("Action items (actions pending)")
    lines.append("")
    return "\n".join(lines)

__all__ = [
    "CLOUD_LABELS",
    "normalize_clouds",
    "parse_date_soft",
    "FeatureRecord",
    "render_header",
    "render_feature_markdown",
]
