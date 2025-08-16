#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, List

# ---------- Cloud helpers ----------

_CLOUD_NORMALIZE = {
    "worldwide (standard multi-tenant)": "General",
    "general": "General",
    "gcc": "GCC",
    "gcc high": "GCC High",
    "gcch": "GCC High",
    "dod": "DoD",
    "department of defense": "DoD",
    "us gov gcc high": "GCC High",
    "us gov dod": "DoD",
}


def normalize_clouds(values: Iterable[str] | None) -> set[str]:
    """
    Accepts None, a single string, or an iterable of strings and returns a set of
    canonical labels: {"General","GCC","GCC High","DoD"}.
    """
    if not values:
        return set()
    out: set[str] = set()
    if isinstance(values, str):
        values = [values]
    for v in values:
        if not v:
            continue
        for piece in str(v).replace(";", ",").split(","):
            name = piece.strip().lower()
            if not name:
                continue
            out.add(_CLOUD_NORMALIZE.get(name, piece.strip()))
    return out


def cloud_display_from(values: Iterable[str] | None) -> str:
    clouds = normalize_clouds(values)
    if not clouds:
        return "—"
    order = ["General", "GCC", "GCC High", "DoD"]
    ordered = [c for c in order if c in clouds]
    extras = [c for c in clouds if c not in order]
    return ", ".join(ordered + extras)


# ---------- Data model ----------

@dataclass
class FeatureRecord:
    public_id: str
    title: str
    product: str
    status: str
    clouds: List[str]
    last_modified: str
    release_date: str
    source: str
    message_id: str
    roadmap_link: str

    # Back-compat aliases (older code may reference these attributes)
    @property
    def PublicId(self) -> str:  # noqa: N802
        return self.public_id

    @property
    def Title(self) -> str:  # noqa: N802
        return self.title

    @property
    def Product_Workload(self) -> str:  # noqa: N802
        return self.product

    @property
    def Status(self) -> str:  # noqa: N802
        return self.status

    @property
    def Cloud_instance(self) -> str:  # noqa: N802
        return cloud_display_from(self.clouds)

    @property
    def LastModified(self) -> str:  # noqa: N802
        return self.last_modified

    @property
    def ReleaseDate(self) -> str:  # noqa: N802
        return self.release_date

    @property
    def Source(self) -> str:  # noqa: N802
        return self.source

    @property
    def MessageId(self) -> str:  # noqa: N802
        return self.message_id

    @property
    def Official_Roadmap_link(self) -> str:  # noqa: N802
        return self.roadmap_link

    @classmethod
    def from_csv_row(cls, row: Mapping[str, Any]) -> "FeatureRecord":
        """
        Flexible mapper from CSV headers (supports both canonical and legacy names).
        """
        def g(*names: str, default: str = "") -> str:
            for n in names:
                if n in row and row[n] is not None:
                    return str(row[n])
            return default

        # Clouds may arrive as "Cloud_instance" or "Clouds", comma/semicolon separated
        raw_clouds = g("Clouds", "Cloud_instance")
        clouds_list = (
            [p.strip() for p in raw_clouds.replace(";", ",").split(",") if p.strip()]
            if raw_clouds
            else []
        )

        pid = g("PublicId", "public_id", "Id", "ID")
        return cls(
            public_id=pid,
            title=g("Title", "title", default=f"[{pid}]"),
            product=g("Product_Workload", "Product", "Workload", "product"),
            status=g("Status", "status"),
            clouds=list(normalize_clouds(clouds_list)),
            last_modified=g("LastModified", "Last Modified", "last_modified"),
            release_date=g("ReleaseDate", "Release Date", "release_date"),
            source=g("Source", "source"),
            message_id=g("MessageId", "message_id"),
            roadmap_link=g("Official_Roadmap_link", "Roadmap", "roadmap_link"),
        )


# ---------- Rendering ----------

_STYLES = """<style>
.rm-wrap { max-width: 980px; margin: 0 auto; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, "Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol"; }
.rm-header h1 { margin: 0.2rem 0 0.1rem 0; font-size: 2rem; }
.rm-meta { color: #555; font-size: 0.95rem; margin-bottom: 0.75rem; }
.rm-toc { border: 1px solid #e6e6e6; border-radius: 12px; padding: 10px 12px; background: #fcfcfc; margin: 10px 0 18px 0; }
.rm-toc h3 { margin: 0 0 6px 0; font-size: 1.05rem; }
.rm-toc ol { margin: 0; padding-left: 18px; }
.rm-toc li { margin: 2px 0; }
.rm-card { border: 1px solid #e6e6e6; border-radius: 12px; padding: 14px 16px; margin: 14px 0; box-shadow: 0 1px 3px rgba(0,0,0,.04); }
.rm-card h3 { margin: 0 0 0.4rem 0; font-size: 1.15rem; line-height: 1.35; }
.rm-table { width: 100%; border-collapse: collapse; margin: 6px 0 10px 0; }
.rm-table th, .rm-table td { border: 1px solid #eee; padding: 6px 8px; font-size: .92rem; vertical-align: top; }
.rm-table th { background: #fafafa; text-align: left; white-space: nowrap; }
.rm-sect { margin: 8px 0; }
.rm-sect h4 { margin: 8px 0 4px; font-size: 1rem; }
.rm-pills { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 8px 0; }
.rm-pill { display: inline-block; padding: 2px 8px; border: 1px solid #e2e2e2; border-radius: 999px; font-size: .80rem; background: #f8f8f8; }
.rm-meta-pills { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 6px 0; }
details.rm-collapsible { margin-top: 8px; }
details.rm-collapsible summary { cursor: pointer; font-weight: 600; }
</style>"""


def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
    return f"""<!-- header -->
{_STYLES}
<div class="rm-wrap rm-header">
  <h1>{title}</h1>
  <div class="rm-meta">
    Generated <strong>{generated_utc}</strong> · Cloud filter: <strong>{cloud_display or "All"}</strong>
  </div>
</div>
"""


def render_toc(features: Sequence[FeatureRecord]) -> str:
    """
    Mini table of contents linking to each feature card by PublicId anchor.
    """
    def _title(f: FeatureRecord) -> str:
        return f.title or f"[{f.public_id}]"

    items = "\n".join(
        f'<li><a href="#rm-{f.public_id}">[{f.public_id}] {_title(f)}</a></li>'
        for f in features
    ) or '<li><em>No items</em></li>'

    return f"""<div class="rm-wrap rm-toc">
  <h3>Contents</h3>
  <ol>
    {items}
  </ol>
</div>
"""


def _fmt(value: str | None) -> str:
    v = (value or "").strip()
    return v if v else "—"


def _split_products(s: str) -> list[str]:
    """
    Split a product/workload string into normalized tokens for pill display.
    Handles '/', ',', ';', '|' as separators and removes empties/dupes (preserving order).
    """
    if not s:
        return []
    raw = s.replace("/", ",").replace(";", ",").replace("|", ",")
    seen: set[str] = set()
    out: list[str] = []
    for piece in (p.strip() for p in raw.split(",") if p.strip()):
        if piece not in seen:
            out.append(piece)
            seen.add(piece)
    return out


def _message_center_link(message_id: str) -> str | None:
    """
    Best-effort deep link to Microsoft 365 Message Center (requires admin sign-in).
    If message_id missing, returns None.
    """
    mid = (message_id or "").strip()
    if not mid:
        return None
    return f"https://admin.microsoft.com/#/MessageCenter/:/messages/{mid}"


def render_feature_markdown(feature: FeatureRecord, ai_sections: Optional[Mapping[str, str]] = None) -> str:
    """
    Render a single feature as a compact card with:
      - bold title + anchor (linked to roadmap if present)
      - product tag pills
      - status / release / clouds meta pills under the title
      - summary table (Message ID hyperlinked to Message Center)
      - collapsible sections (What’s changing / Impact / Action items)
      - source links shown under Summary (Roadmap + Message Center)
    """
    fid = _fmt(feature.public_id)
    title_txt = feature.title or f"[{fid}]"
    roadmap_url = (feature.roadmap_link or "").strip()
    heading = f"<strong>{title_txt}</strong>"
    if roadmap_url:
        heading = f'<strong><a href="{roadmap_url}">{title_txt}</a></strong>'

    product = _fmt(feature.product)
    status = _fmt(feature.status)
    clouds = cloud_display_from(feature.clouds) or "—"
    modified = _fmt(feature.last_modified)
    release = _fmt(feature.release_date)
    source = _fmt(feature.source)
    msgid = _fmt(feature.message_id)

    # Product pills
    pills = "".join(f'<span class="rm-pill">{p}</span>' for p in _split_products(feature.product))

    # Meta pills (Status / Release / Clouds)
    meta_pills = "".join(
        [
            f'<span class="rm-pill"><strong>Status:</strong> {status}</span>',
            f'<span class="rm-pill"><strong>Release:</strong> {release}</span>',
            f'<span class="rm-pill"><strong>Clouds:</strong> {clouds}</span>',
        ]
    )

    # Message ID → hyperlink to Message Center (when present)
    mc_link = _message_center_link(feature.message_id)
    msg_cell = f'<a href="{mc_link}">{msgid}</a>' if mc_link else msgid

    # AI sections (optional)
    ai = ai_sections or {}
    summary = ai.get("summary") or "*summary pending*"
    changes = ai.get("changes") or "*details pending*"
    impact = ai.get("impact") or "*impact pending*"
    actions = ai.get("actions") or "*actions pending*"

    # Source links under Summary
    src_parts: list[str] = []
    if roadmap_url:
        src_parts.append(f'<a href="{roadmap_url}">Official Roadmap</a>')
    if mc_link:
        src_parts.append(f'<a href="{mc_link}">Message Center</a>')
    sources_line = " | ".join(src_parts) if src_parts else "—"

    return f"""<div class="rm-wrap rm-card" id="rm-{fid}">
<h3>{heading}</h3>

<div class="rm-meta-pills">{meta_pills}</div>
<div class="rm-pills" aria-label="Products">{pills or '<span class="rm-pill">Unspecified</span>'}</div>

<table class="rm-table">
  <tr><th>Roadmap ID</th><td>{fid}</td><th>Status</th><td>{status}</td></tr>
  <tr><th>Product / Workload</th><td>{product}</td><th>Cloud(s)</th><td>{clouds}</td></tr>
  <tr><th>Last Modified</th><td>{modified}</td><th>Release Date</th><td>{release}</td></tr>
  <tr><th>Source</th><td>{source}</td><th>Message ID</th><td>{msg_cell}</td></tr>
</table>

<div class="rm-sect">
  <h4>Summary</h4>
  <div>{summary}</div>
  <div style="margin-top:6px;font-size:.9rem;color:#555;">Sources: {sources_line}</div>
</div>

<details class="rm-collapsible">
  <summary>What’s changing</summary>
  <div class="rm-sect">{changes}</div>
</details>

<details class="rm-collapsible">
  <summary>Impact and rollout</summary>
  <div class="rm-sect">{impact}</div>
</details>

<details class="rm-collapsible">
  <summary>Action items</summary>
  <div class="rm-sect">{actions}</div>
</details>

</div>
"""
