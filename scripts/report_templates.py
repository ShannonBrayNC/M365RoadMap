#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Set, Dict, List

# Canonical cloud labels we use everywhere in the report
# "Worldwide (Standard Multi-Tenant)" and related inputs map to "General".
_CLOUD_SYNONYMS: Dict[str, str] = {
    "worldwide (standard multi-tenant)": "General",
    "world wide (standard multi-tenant)": "General",
    "worldwide": "General",
    "world wide": "General",
    "commercial": "General",
    "general": "General",

    "gcc": "GCC",
    "government community cloud": "GCC",

    "gcc high": "GCC High",
    "gcch": "GCC High",
    "government community cloud high": "GCC High",

    "dod": "DoD",
    "department of defense": "DoD",
}


def normalize_clouds(values: Iterable[str] | str | None) -> Set[str]:
    """
    Accept a single string or iterable of strings that might be:
      - Canonical labels: "General", "GCC", "GCC High", "DoD"
      - Display strings: "Worldwide (Standard Multi-Tenant)"
      - Comma/pipe-separated fields (e.g., CSV cell from master)
    Return a set of canonical labels.
    """
    if not values:
        return set()

    if isinstance(values, str):
        raw: List[str] = [v.strip() for v in values.replace("|", ",").split(",")]
    else:
        raw = []
        for v in values:
            if v is None:
                continue
            raw.extend([t.strip() for t in str(v).replace("|", ",").split(",")])

    out: Set[str] = set()
    for v in raw:
        if not v:
            continue
        k = v.strip().lower()
        canon = _CLOUD_SYNONYMS.get(k)
        if canon:
            out.add(canon)
        else:
            # If already canonical (e.g., "GCC High") keep as-is
            out.add(v.strip())
    return out


@dataclass
class FeatureRecord:
    """
    Unified feature record used by generate_report.py. All fields are snake_case.

    Note: This intentionally diverges from CSV column case. The report generator
    maps CSV headers like 'PublicId', 'Cloud_instance' into these attributes.
    """
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


def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
    """
    Render the report header. 'cloud_display' should be a human-readable summary
    such as 'General' or 'General, GCC'.
    """
    return (
        f"{title}\n"
        f"Generated {generated_utc}\n\n"
        f"{title} Generated {generated_utc} Cloud filter: {cloud_display}\n"
    )


def render_feature_markdown(
    rec: FeatureRecord,
    ai_sections: Optional[dict[str, str]] = None,
) -> str:
    """
    Render a single feature section. 'ai_sections' can provide four keys:
    'summary', 'changes', 'impact', 'actions' – we'll fallback to readable
    defaults if missing.
    """
    ai_sections = ai_sections or {}
    summary = ai_sections.get("summary", "Summary (summary pending)")
    changes = ai_sections.get("changes", "What’s changing (details pending)")
    impact = ai_sections.get("impact", "Impact and rollout (impact pending)")
    actions = ai_sections.get("actions", "Action items (actions pending)")

    cloud_disp = ", ".join(sorted(rec.clouds)) if rec.clouds else "—"
    rm = rec.roadmap_link or (
        f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rec.public_id}"
        if rec.public_id else ""
    )

    header_line = (
        f"[{rec.public_id}] {rec.title} "
        f"Product/Workload: {rec.product or '—'} "
        f"Status: {rec.status or '—'} "
        f"Cloud(s): {cloud_disp} "
        f"Last Modified: {rec.last_modified or '—'} "
        f"Release Date: {rec.release_date or '—'} "
        f"Source: {rec.source or '—'} "
        f"Message ID: {rec.message_id or '—'} "
        f"Official Roadmap: {rm}"
    ).strip()

    parts = [
        header_line,
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
