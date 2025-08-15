#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


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
        if k in d and str(d[k]).strip():
            return str(d[k]).strip()
    return default


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
    # stable order, de-duped
    ordered = [c for c in CLOUD_LABELS if c in set(out)]
    return ordered


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
        fid = _first(row, "id", "Id", "ID", "FeatureId", "Feature ID", default="")
        title = _first(row, "title", "Title", "feature_name", "Feature")
        product = _first(row, "product", "Product", "workload")
        status = _first(row, "status", "Status", "state", "Lifecycle")
        release_phase = _first(row, "releasePhase", "Release phase", "phase")
        eta = _first(row, "releaseDate", "Release date", "eta", "Targeted Release")
        clouds_raw = _first(
            row, "cloud", "Cloud", "clouds", "Cloud Instances", "Clouds"
        )
        clouds = normalize_clouds(clouds_raw)
        updated = _first(
            row,
            "lastModifiedDateTime",
            "Last modified",
            "modified",
            "Last Updated",
            "updated",
        )
        src = _first(row, "source", "Source")
        # Prefer provided link else manufacture Roadmap link
        link = _first(row, "link", "Link", "url", "URL")
        if not link and fid:
            link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=searchterms={fid}"
        # Summary/description-ish
        summary = _first(row, "summary", "Summary", "description", "Description", "body")
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
        # Minimal, stable payload for parser
        d = asdict(self)
        # keep only primitives the parser filters on
        meta = {
            "id": d["id"],
            "title": d["title"],
            "product": d["product"],
            "status": d["status"],
            "release_phase": d["release_phase"],
            "eta": d["eta"],
            "clouds": d["clouds"] or [],
            "updated": d["updated"],
            "link": d["link"],
            "source": d["source"],
        }
        import json

        return json.dumps(meta, ensure_ascii=False, separators=(",", ":"))

    def render_markdown(self) -> str:
        # checkbox list (visual only)
        ck = []
        have = set(self.clouds or [])
        for label in CLOUD_LABELS:
            ck.append(f"- [{'x' if label in have else ' '}] {label}")
        clouds_line = ", ".join(self.clouds or [])
        # Header & meta
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
