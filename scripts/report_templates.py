#!/usr/bin/env python3
from __future__ import annotations

import dataclasses as dc
import datetime as dt
import html
import re
from typing import Dict, Iterable, Optional, Sequence, Set


# -------- Cloud helpers (shared shape with generate_report) --------
CLOUD_LABELS = ("General", "GCC", "GCC High", "DoD")


def normalize_clouds(raw: Optional[str | Sequence[str]]) -> Set[str]:
    """
    Normalize any 'cloud' field into canonical tags:
    {"General","GCC","GCC High","DoD"}.
    Accepts comma/semicolon/pipe/slash separated strings and common synonyms.
    """
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple)):
        parts = []
        for x in raw:
            parts.extend(re.split(r"[;,/|,]", str(x)))
    else:
        parts = re.split(r"[;,/|,]", str(raw))

    tags: Set[str] = set()
    for p in parts:
        c = p.strip().lower()
        if not c:
            continue

        # Treat multiple synonyms as "General"
        if any(k in c for k in ("worldwide", "standard multi-tenant", "commercial", "public", "general")):
            tags.add("General")

        # GCC High first (so it doesn't get swallowed by "gcc")
        if "gcc high" in c or c == "gcch" or "us gov gcc high" in c:
            tags.add("GCC High")

        # DoD
        if "dod" in c or "do d" in c or "us gov dod" in c:
            tags.add("DoD")

        # GCC (broad substring, but skip ones already caught as High)
        if "gcc" in c and "high" not in c:
            tags.add("GCC")

    return tags


# -------- Data model --------
@dc.dataclass(slots=True)
class FeatureRecord:
    public_id: str
    title: str
    product_workload: str
    status: str
    last_modified: str
    release_date: str
    cloud_raw: str
    official_link: str
    source: str
    message_id: str

    # derived
    clouds: Set[str] = dc.field(default_factory=set)

    @staticmethod
    def from_row(row: Dict[str, str]) -> "FeatureRecord":
        # Accept the headers you showed in Check-ReportHeaders
        pub = (row.get("PublicId") or row.get("Public_ID") or "").strip()
        title = (row.get("Title") or "").strip()
        workload = (row.get("Product_Workload") or row.get("Workload") or "").strip()
        status = (row.get("Status") or "").strip()
        last_modified = (row.get("LastModified") or row.get("Last_Modified") or "").strip()
        release_date = (row.get("ReleaseDate") or row.get("Release_Date") or "").strip()
        cloud_raw = (row.get("Cloud_instance") or row.get("Cloud") or "").strip()
        official = (row.get("Official_Roadmap_link") or row.get("Roadmap_Link") or "").strip()
        source = (row.get("Source") or "").strip()
        mid = (row.get("MessageId") or row.get("Message_ID") or "").strip()

        clouds = normalize_clouds(cloud_raw)
        return FeatureRecord(
            public_id=pub,
            title=title,
            product_workload=workload,
            status=status,
            last_modified=last_modified,
            release_date=release_date,
            cloud_raw=cloud_raw,
            official_link=official,
            source=source,
            message_id=mid,
            clouds=clouds,
        )

    # -------- Markdown scaffold (STRICT — parser relies on this) --------
    def render_markdown(self) -> str:
        """
        Emit a fixed scaffold the parser can read 1:1.
        Keep headings and bold labels EXACT — parser uses them.
        """
        # Escape only what could break formatting if present
        esc = lambda s: s.replace("\r", "").strip()

        meta_lines = [
            f"**Product/Workload:** {esc(self.product_workload) or '—'}",
            f"**Status:** {esc(self.status) or '—'}",
            f"**Cloud(s):** {', '.join(sorted(self.clouds)) if self.clouds else (esc(self.cloud_raw) or '—')}",
            f"**Last Modified:** {esc(self.last_modified) or '—'}",
            f"**Release Date:** {esc(self.release_date) or '—'}",
            f"**Source:** {esc(self.source) or '—'}",
            f"**Message ID:** {esc(self.message_id) or '—'}",
            f"**Official Roadmap:** {esc(self.official_link) or '—'}",
        ]

        # Title line: include the ID in square brackets so parsing is unambiguous
        header = f"## [{self.public_id}] {esc(self.title) or 'Untitled Feature'}"

        # Section placeholders — downstream may overwrite but we keep them stable
        sections = [
            "### Summary\n_(summary pending)_",
            "### What’s changing\n_(details pending)_",
            "### Impact and rollout\n_(impact pending)_",
            "### Action items\n_(actions pending)_",
        ]

        return "\n".join(
            [
                header,
                *meta_lines,
                "",
                *sections,
                "",  # trailing newline between features
            ]
        )


# -------- Simple date helpers (used by generator and parser) --------
def parse_date_soft(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    s = s.strip()
    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%m/%d/%Y",
    ]
    for fmt in fmts:
        try:
            return dt.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None
