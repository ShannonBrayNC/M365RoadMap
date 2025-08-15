from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


def _dash(v: Optional[str]) -> str:
    v = (v or "").strip()
    return v if v else "—"


@dataclass
class FeatureRecord:
    public_id: str
    title: str
    product_workload: Optional[str] = None
    status: Optional[str] = None
    clouds_display: Optional[str] = None
    last_modified: Optional[str] = None
    release_date: Optional[str] = None
    source: Optional[str] = None
    message_id: Optional[str] = None
    official_url: Optional[str] = None

    # New, populated by the generator:
    summary: Optional[str] = None
    whats_changing: Optional[str] = None
    impact_rollout: Optional[str] = None
    action_items: Optional[str] = None


def render_header(title: str, generated_utc: str, cloud_display: str, total_features: int) -> str:
    lines = []
    lines.append(f"Generated {generated_utc}")
    lines.append(title)
    lines.append(f"Generated {generated_utc} Cloud filter: {cloud_display}")
    lines.append("")
    lines.append(f"Total features: {total_features}")
    lines.append("")
    return "\n".join(lines)


def _section(label: str, body: Optional[str]) -> str:
    return f"{label}\n{(body or '(pending)')}\n"


def render_feature_markdown(fr: FeatureRecord) -> str:
    header = f"[{fr.public_id}] {fr.title}"
    meta = (
        f"Product/Workload: {_dash(fr.product_workload)} "
        f"Status: {_dash(fr.status)} "
        f"Cloud(s): {_dash(fr.clouds_display)} "
        f"Last Modified: {_dash(fr.last_modified)} "
        f"Release Date: {_dash(fr.release_date)} "
        f"Source: {_dash(fr.source)} "
        f"Message ID: {_dash(fr.message_id)} "
        f"Official Roadmap: {_dash(fr.official_url)}"
    )

    parts = [
        header,
        meta,
        "",
        _section("Summary", fr.summary),
        _section("What’s changing", fr.whats_changing),
        _section("Impact and rollout", fr.impact_rollout),
        _section("Action items", fr.action_items),
    ]

    return "\n".join(parts) + "\n"
