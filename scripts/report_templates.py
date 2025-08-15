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
    release_phase: str = ""
    release_window: str = ""
    last_modified: str = ""
    description: str = ""
    sources: Sequence[str] = ()
    ms_roadmap_url: str = ""

    @staticmethod
    def from_row(row: Dict[str, str]) -> "FeatureRecord":
        def g(*keys: str, default: str = "") -> str:
            for k in keys:
                v = row.get(k)
                if v is not None:
                    return str(v).strip()
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

        ms_roadmap_url = f"https://www.microsoft.com/microsoft-365/roadmap?searchterms={fid}" if fid else ""
        src = g("source", default="")
        sources = [s.strip() for s in src.split(",") if s.strip()] if src else ()

        return FeatureRecord(
            fid=fid, title=title, workload=workload, status=status, cloud=cloud,
            release_phase=release_phase, release_window=release_window,
            last_modified=last_modified, description=description,
            sources=sources, ms_roadmap_url=ms_roadmap_url,
        )

def _fmt_nonempty(label: str, value: str) -> str:
    value = (value or "").strip()
    return f"**{label}:** {value}" if value else ""

def _lines_join(*parts: str) -> str:
    return " — ".join([p for p in parts if p])

def render_feature_markdown(fr: FeatureRecord, now: Optional[datetime] = None) -> str:
    now = now or datetime.utcnow()
    header = f"## {fr.title or '(Untitled Feature)'} — _Roadmap ID {fr.fid or '?'}_"

    meta_line = _lines_join(
        _fmt_nonempty("Status", fr.status or fr.release_phase),
        _fmt_nonempty("Release window", fr.release_window),
        _fmt_nonempty("Clouds", fr.cloud),
        _fmt_nonempty("Workload", fr.workload),
        _fmt_nonempty("Last modified", fr.last_modified),
    )

    what_it_is = fr.description.strip() or "Microsoft has not published additional description yet."

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

    confirmed = []
    if fr.status or fr.release_phase:
        confirmed.append(f"Status: {fr.status or fr.release_phase}")
    if fr.release_window:
        confirmed.append(f"Target window: {fr.release_window}")
    if fr.cloud:
        confirmed.append(f"Cloud/Instance: {fr.cloud}")
    if fr.workload:
        confirmed.append(f"Workload: {fr.workload}")

    inferred = [
        "Final UI entry points and labels may change before GA.",
        "Storage and eDiscovery specifics often arrive with GA docs.",
    ]

    usage_steps = [
        "Open the relevant Teams chat or app area where the feature appears.",
        "Create and co-edit content; use @mentions to notify collaborators (where applicable).",
        "Rely on membership-based access; sharing follows tenant policy.",
    ]

    admin_items = [
        "Validate Messaging/Meeting (or corresponding) policies for collaboration readiness.",
        "Confirm retention and eDiscovery posture in Microsoft Purview aligns with expected content.",
        "Review data residency requirements for impacted workloads.",
    ]

    comparisons = [
        "Compare with Loop components for lightweight co-editing.",
        "Compare with Collaborative Meeting Notes for meeting-scoped scenarios.",
    ]

    checklist = [
        "Identify pilot users or champions.",
        "Confirm policies and compliance posture.",
        "Publish a 1-pager with 'where it is' and 'how to use it' for end users.",
    ]

    open_items = [
        "Confirm GA storage location & retention handling.",
        "Document exact UI entry points and admin toggles, if any.",
    ]

    links = [f"- **Roadmap entry**: {fr.ms_roadmap_url}"] if fr.ms_roadmap_url else []

    tl_dr = [
        f"**What:** {fr.title or 'Feature'} scoped to {fr.workload or 'Microsoft 365'}.",
        f"**When:** {fr.release_window or 'Date TBA'}; {fr.status or fr.release_phase or ''}".strip(),
        f"**Prep:** Ensure collaboration policies and compliance posture are set.",
    ]

    out = []
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
    if confirmed:
        out.append("- **Confirmed**")
        out += [f"  - {c}" for c in confirmed]
    if inferred:
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
    out += links if links else ["- (Will add roadmap/support links when available.)"]
    out.append("")
    out.append("### TL;DR")
    out += [f"- {t}" for t in tl_dr]
    out.append("")
    return "\n".join(out)
