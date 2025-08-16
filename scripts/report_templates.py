from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

# ---- Cloud helpers expected by other scripts ----
CLOUD_LABELS: dict[str, str] = {
    "General": "Worldwide (Standard Multi-Tenant)",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
    "Worldwide (Standard Multi-Tenant)": "Worldwide (Standard Multi-Tenant)",
}


def normalize_clouds(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s:
        return "—"
    # handle common variants
    if s.lower().startswith("world"):
        return CLOUD_LABELS["General"]
    return CLOUD_LABELS.get(s, s)


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def parse_date_soft(value: str | None) -> str:
    """
    Try to normalize various date-ish inputs to YYYY-MM-DD.
    If parsing fails, return the original string (or '—' if empty).
    """
    s = (value or "").strip()
    if not s:
        return "—"
    # Quick pass: already YYYY-MM-DD...
    if _ISO_RE.match(s):
        return s[:10]
    # Handle Zulu / offsets
    s2 = s.replace("Z", "+00:00") if "Z" in s and "+" not in s else s
    try:
        dt_obj = dt.datetime.fromisoformat(s2)
        return dt_obj.date().isoformat()
    except Exception:
        pass
    # Try common US/EU patterns?
    for fmt in ("%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            continue
    return s


# ---- Markdown rendering (for generate_report.py) ----


def _dash(v: str | None) -> str:
    v = (v or "").strip()
    return v if v else "—"


@dataclass
class FeatureRecord:
    public_id: str
    title: str
    product_workload: str | None = None
    status: str | None = None
    clouds_display: str | None = None
    last_modified: str | None = None
    release_date: str | None = None
    source: str | None = None
    message_id: str | None = None
    official_url: str | None = None
    # Filled from Message Center body extraction:
    summary: str | None = None
    whats_changing: str | None = None
    impact_rollout: str | None = None
    action_items: str | None = None


def render_header(title: str, generated_utc: str, cloud_display: str, total_features: int) -> str:
    lines = []
    lines.append(f"Generated {generated_utc}")
    lines.append(title)
    lines.append(f"Generated {generated_utc} Cloud filter: {cloud_display}")
    lines.append("")
    lines.append(f"Total features: {total_features}")
    lines.append("")
    return "\n".join(lines)


def _section(label: str, body: str | None) -> str:
    return f"{label}\n{(body or '(pending)')}\n"


def render_feature_markdown(
    rec: FeatureRecord,
    *,
    summary: str | None = None,
    changes: str | None = None,
    impact: str | None = None,
    actions: str | None = None,
) -> str:
    """
    Render one feature card. If section strings are provided, use them;
    otherwise render the legacy '(… pending)' placeholders.
    """
    header = (
        f"[{rec.PublicId}] {rec.Title}\n"
        f"Product/Workload: {rec.Product_Workload or '—'} "
        f"Status: {rec.Status or '—'} "
        f"Cloud(s): {rec.Cloud_instance or '—'} "
        f"Last Modified: {rec.LastModified or '—'} "
        f"Release Date: {rec.ReleaseDate or '—'} "
        f"Source: {rec.Source or '—'} "
        f"Message ID: {rec.MessageId or '—'} "
        f"Official Roadmap: {rec.Official_Roadmap_link or '—'}\n"
    )

    def sect(title: str, body: str | None, placeholder: str) -> str:
        return f"\n{title}\n{body if (body and body.strip()) else f'({placeholder})'}\n"

    return (
        header
        + sect("Summary", summary, "summary pending")
        + sect("What’s changing", changes, "details pending")
        + sect("Impact and rollout", impact, "impact pending")
        + sect("Action items", actions, "actions pending")
    )
