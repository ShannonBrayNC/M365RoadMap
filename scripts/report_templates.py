#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List

CLOUD_LABELS = ("General", "GCC", "GCC High", "DoD")
WORLDWIDE_SYNONYMS = {
    "Worldwide (Standard Multi-Tenant)",
    "Worldwide",
    "Standard Multi-Tenant",
    "General",
    "WW",
    "Public",
}

def _first(d: Dict, *keys, default: str = "") -> str:
    for k in keys:
        if k in d:
            v = str(d[k]).strip()
            if v:
                return v
    return default

def _first_contains(d: Dict, needle: str) -> str:
    n = needle.lower()
    for k in d.keys():
        if n in k.lower():
            v = str(d.get(k, "")).strip()
            if v:
                return v
    return ""

def normalize_clouds(raw: str | None) -> List[str]:
    if not raw:
        return []
    parts = {p.strip() for p in str(raw).replace(";", ",").split(",")}
    out: List[str] = []
    for p in parts:
        if not p:
            continue
        if p in WORLDWIDE_SYNONYMS:
            out.append("General")
        elif p in {"GCC", "US Gov GCC"}:
            out.append("GCC")
        elif p in {"GCC High", "US Gov GCC High", "GCCH"}:
            out.append("GCC High")
        elif p in {"DoD", "US Gov DoD"}:
            out.append("DoD")
    return [c for c in CLOUD_LABELS if c in set(out)]

@dataclass
class FeatureRecord:
    id: str
    title: str = ""
    product: str = ""
    status: str = ""
    release_phase: str = ""
    eta: str = ""
    clouds: List[str] | None = None
    updated: str = ""
    source: str = ""
    summary: str = ""
    link: str = ""

    @staticmethod
    def from_row(row: Dict) -> "FeatureRecord":
        fid = _first(
            row,
            "PublicId",
            "MessageId",
            "id",
            "Id",
            "ID",
            "FeatureId",
            "Feature ID",
            "FeatureID",
            "Roadmap ID",
            "RoadmapId",
            "RoadmapID",
            default="",
        )

        title = _first(row, "Title", "title", "feature_name", "Feature", "Feature Name")
        if not title:
            title = _first_contains(row, "title")

        product = _first(row, "Product_Workload", "product", "Product", "workload", "Workload", "Service")
        if not product:
            product = _first_contains(row, "product")

        status = _first(row, "Status", "status", "state", "Lifecycle", "Release status")
        if not status:
            status = _first_contains(row, "status")

        release_phase = _first(row, "Release phase", "releasePhase", "phase", "Phase")
        if not release_phase:
            release_phase = _first_contains(row, "phase")

        eta = _first(
            row,
            "ReleaseDate",
            "releaseDate",
            "Release date",
            "eta",
            "ETA",
            "Targeted Release",
            "GA Date",
        )
        if not eta:
            eta = _first_contains(row, "date")

        clouds_raw = _first(
            row,
            "Cloud_instance",
            "cloud",
            "Cloud",
            "clouds",
            "Clouds",
            "Cloud Instance(s)",
            "Cloud Instance(s) Supported",
            "Cloud Instance(s) availability",
        )
        if not clouds_raw:
            clouds_raw = _first_contains(row, "cloud")
        clouds = normalize_clouds(clouds_raw)

        updated = _first(
            row,
            "LastModified",
            "lastModifiedDateTime",
            "Last modified",
            "Last Modified",
            "modified",
            "Last Updated",
            "updated",
            "Update Date",
        )
        if not updated:
            updated = _first_contains(row, "modified")

        src = _first(row, "Source", "source", "Feed", "Origin")

        link = _first(row, "Official_Roadmap_link", "link", "Link", "url", "URL")
        if not link and fid:
            link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=searchterms={fid}"

        summary = _first(row, "summary", "Summary", "description", "Description", "body")
        if not summary:
            summary = _first_contains(row, "description")

        return FeatureRecord(
            id=str(fid),
            title=title,
            product=product,
            status=status,
            release_phase=release_phase,
            eta=eta,
            clouds=clouds,
            updated=updated,
            source=src,
            summary=summary,
            link=link,
        )

    def to_meta_json(self) -> str:
        from json import dumps
        meta = {
            "id": self.id,
            "title": self.title,
            "product": self.product,
            "status": self.status,
            "release_phase": self.release_phase,
            "eta": self.eta,
            "clouds": self.clouds or [],
            "updated": self.updated,
            "link": self.link,
            "source": self.source,
        }
        return dumps(meta, ensure_ascii=False, separators=(",", ":"))

    def render_markdown(self) -> str:
        ck = []
        have = set(self.clouds or [])
        for label in CLOUD_LABELS:
            ck.append(f"- [{'x' if label in have else ' '}] {label}")
        clouds_line = ", ".join(self.clouds or [])
        buf = []
        buf.append(f"## Feature {self.id} — {self.title or '(untitled)'}")
        buf.append("")
        buf.append(
            f"> **Product:** {self.product or '—'}  "
            f"**Clouds:** {clouds_line or '—'}  "
            f"**Status:** {self.status or '—'}  "
            f"**Phase:** {self.release_phase or '—'}  "
            f"**ETA:** {self.eta or '—'}"
        )
        buf.append(
            f"> **Updated:** {self.updated or '—'}  "
            f"**Source:** {self.source or '—'}  "
            f"**Link:** {self.link or '—'}"
        )
        buf.append(f"<!-- FEATURE:{self.id}:START -->")
        buf.append(f"<!-- META {self.to_meta_json()} -->")
        buf.append("")
        buf.append("### Summary")
        buf.append(self.summary or "_No summary available._")
        buf.append("")
        buf.append("### Change Impact")
        buf.append("_Author notes here._")
        buf.append("")
        buf.append("### Tenant Availability")
        buf.extend(ck)
        buf.append("")
        buf.append("### Links")
        if self.link:
            buf.append(f"- Roadmap: {self.link}")
        buf.append(f"<!-- FEATURE:{self.id}:END -->")
        buf.append("")
        return "\n".join(buf)
