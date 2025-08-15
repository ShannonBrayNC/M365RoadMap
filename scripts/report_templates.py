#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Sequence


@dataclass
class FeatureRecord:
    fid: str
    title: str
    workload: str = ""
    status: str = ""
    cloud: str = ""
    release_phase: str = ""      # e.g., "In development", "Rolling out"
    release_window: str = ""     # e.g., "September CY2025"
    last_modified: str = ""      # ISO or free-form
    description: str = ""        # official roadmap description if present
    sources: Sequence[str] = ()  # e.g., ["graph","public-json","rss"]
    ms_roadmap_url: str = ""     # constructed if not provided

    @staticmethod
    def from_row(row: Dict[str, str]) -> "FeatureRecord":
        # Defensive getter, accepts multiple possible column names
        def g(*keys: str, default: str = "") -> str:
            for k in keys:
                if k in row and row[k] is not None:
                    return str(row[k]).strip()
            return default

        fid = g("feature_id", "roadmap_id", "id")
        title = g("title", "feature_title")
        workload = g("workload")
        status = g("status")
        cloud = g("cloud", "clouds", "tenant_cloud", "tenantCloud")
        release_phase = g("releasePhase", "phase")
        release_window = g("releaseDate", "target", "target_release", "release_window")
        last_modified = g("lastModified", "last_modified", "lastModifiedDateTime")
        description = g("description", "body_text", "body")

        url = f"https://www.microsoft.com/microsoft-365/roadmap?searchterms={fid}" if fid else ""

        src = g("source", default="")
        sources = [s.strip() for s in src.split(",") if s.strip()] if src else ()

        return FeatureRecord(
            fid=fid,
            title=title,
            workload=workload,
            status=status,
            cloud=cloud,
            release_phase=release_phase,
            release_window=release_window,
            last_modified=last_modified,
            description=description,
            sources=sources,
            ms_roadmap_url=url,
        )


def _fmt_nonempty(label: str, value: str) -> str:
    v = (value or "").strip()
    return f"**{label}:** {v}" if v else ""


def _lines_join(*parts: str) -> str:
    return " — ".join([p for p in parts if p])


def render_feature_markdown(fr: FeatureRecord, now: Optional[datetime] = None) -> str:
    """
    Render one feature section to Markdown in a fixed scaffold:

    ## Title — _Roadmap ID 498159_
    Status/Window/Cloud/Workload/Last modified (inline)
    ### What it is (confirmed)
    ### Why it matters
    ### What’s confirmed vs. what’s inferred
    ### How you’ll use it (practical workflow)
    ### Admin & Governance: what to set up now
    ### Comparison with adjacent features
    ### Day-one checklist
    ### Open items to verify at GA
    ### Official Microsoft links
    ### TL;DR
    """
    now = now or datetime.utcnow()
    fid = fr.fid or "?"
    anchor = f'<a id="feature-{fid}"></a>'  # stable anchor for TOC links

    header = f"## {fr.title or '(Untitled Feature)'} — _Roadmap ID {fid}_"

    meta_line = _lines_join(
        _fmt_nonempty("Status", fr.status or fr.release_phase),
        _fmt_nonempty("Release window", fr.release_window or "TBA"),
        _fmt_nonempty("Clouds", fr.cloud or "Unspecified"),
        _fmt_nonempty("Workload", fr.workload or "Unspecified"),
        _fmt_nonempty("Last modified", fr.last_modified or "Unknown"),
    )

    # Always render every section (fixed scaffold). Use helpful defaults.
    what_it_is = (fr.description or "").strip() or "Microsoft has not published additional description yet."

    why_matters_bullets = []
    if "Teams" in (fr.workload or "") or "Teams" in (fr.title or ""):
        why_matters_bullets += [
            "Centralizes collaboration in-context with the chat/channel.",
            "Reduces scattered docs/notes and drives shared visibility.",
        ]
    if not why_matters_bullets:
        why_matters_bullets = [
            "Improves collaboration and reduces context switching.",
            "Aligns with Microsoft 365 governance and sharing controls.",
        ]

    confirmed = [
        f"Status: {fr.status or fr.release_phase or 'TBA'}",
        f"Target window: {fr.release_window or 'TBA'}",
        f"Cloud/Instance: {fr.cloud or 'Unspecified'}",
        f"Workload: {fr.workload or 'Unspecified'}",
    ]

    inferred = [
        "Final UI entry points and labels may change before GA.",
        "Storage and eDiscovery specifics often arrive with GA docs.",
    ]

    usage_steps = [
        "Open the Teams area/app where the feature appears (or relevant M365 surface).",
        "Create and co-edit content; use @mentions to notify collaborators (where applicable).",
        "Access follows membership and tenant data sharing policy.",
    ]

    admin_items = [
        "Validate messaging/meeting (or workload-specific) policies for collaboration readiness.",
        "Confirm Microsoft Purview retention/eDiscovery posture aligns with expected content.",
        "Review data residency requirements for impacted workloads.",
    ]

    comparisons = [
        "Compare with Loop components for lightweight co-editing.",
        "Compare with Collaborative Meeting Notes for meeting-scoped scenarios.",
    ]

    checklist = [
        "Identify pilot users or champions.",
        "Confirm policies and compliance posture.",
        "Publish a 1-pager with where to find it and how to use it for end users.",
    ]

    open_items = [
        "Confirm GA storage location & retention handling.",
        "Document exact UI entry points and admin toggles, if any.",
    ]

    links = [f"- **Roadmap entry**: {fr.ms_roadmap_url}"] if fr.ms_roadmap_url else [
        "- (Add roadmap/support links when available.)"
    ]

    tl_dr = [
        f"**What:** {fr.title or 'Feature'} scoped to {fr.workload or 'Microsoft 365'}.",
        f"**When:** {fr.release_window or 'Date TBA'}; {fr.status or fr.release_phase or 'Status TBA'}",
        f"**Prep:** Ensure collaboration policies and compliance posture are set.",
    ]

    out: list[str] = []
    out.append(anchor)
    out.append(header)
    if meta_line:
        out.append(meta_line)
    out.append("")
    out.append("### What it is (confirmed)")
    out.append(what_it_is)
    out.append("")
    out.append("### Why it matters")
    out += [f"- {b}" for b in why_matters_bullets]
    out.append("")
    out.append("### What’s confirmed vs. what’s inferred")
    out.append("- **Confirmed**")
    out += [f"  - {c}" for c in confirmed]
    out.append("- **Inferred / To validate**")
    out += [f"  - {i}" for i in inferred]
    out.append("")
    out.append("### How you’ll use it (practical workflow)")
    out += [f"1. {s}" for s in usage_steps]
    out.append("")
    out.append("### Admin & Governance: what to set up now")
    out += [f"- {a}" for a in admin_items]
    out.append("")
    out.append("### Comparison with adjacent features")
    out += [f"- {c}" for c in comparisons]
    out.append("")
    out.append("### Day-one checklist")
    out += [f"- {c}" for c in checklist]
    out.append("")
    out.append("### Open items to verify at GA")
    out += [f"- {o}" for o in open_items]
    out.append("")
    out.append("### Official Microsoft links")
    out += links
    out.append("")
    out.append("### TL;DR")
    out += [f"- {t}" for t in tl_dr]
    out.append("")
    out.append("---")  # clear divider between features
    out.append("")
    return "\n".join(out)
