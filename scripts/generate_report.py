#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

# stdlib
import argparse
import csv
import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

# ---------------------------------------------------------------------
# Import path shim: ensure sibling imports work when run as a path
# ---------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

# ---------------------------------------------------------------------
# Import report templates utilities (prefer same-folder import; fall back
# to package-style when run via `python -m scripts.generate_report`)
# ---------------------------------------------------------------------
try:
    from report_templates import (  # type: ignore
        FeatureRecord,
        render_header,
        render_feature_markdown,
        normalize_clouds,
        CLOUD_LABELS,
    )
except Exception:
    from scripts.report_templates import (  # type: ignore[no-redef]
        FeatureRecord,
        render_header,
        render_feature_markdown,
        normalize_clouds,
        CLOUD_LABELS,
    )

# ---------------------------------------------------------------------
# Canonical CSV headers produced by fetch_messages_graph.py
# ---------------------------------------------------------------------
MASTER_HEADERS: list[str] = [
    "PublicId",
    "Title",
    "Source",
    "Product_Workload",
    "Status",
    "LastModified",
    "ReleaseDate",
    "Cloud_instance",
    "Official_Roadmap_link",
    "MessageId",
]

# Friendly aliases that we normalize back to canonical headers
HEADER_ALIASES: dict[str, str] = {
    "publicid": "PublicId",
    "title": "Title",
    "source": "Source",
    "product_workload": "Product_Workload",
    "product / workload": "Product_Workload",
    "status": "Status",
    "lastmodified": "LastModified",
    "last modified": "LastModified",
    "releasedate": "ReleaseDate",
    "release date": "ReleaseDate",
    "cloud_instance": "Cloud_instance",
    "cloud instance": "Cloud_instance",
    "official_roadmap_link": "Official_Roadmap_link",
    "official roadmap link": "Official_Roadmap_link",
    "messageid": "MessageId",
    "message id": "MessageId",
}

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
_DASH = "—"


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "section"


def _split_csv_like(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,\|]+", value)
    return [p.strip() for p in parts if p.strip()]


def _coalesce(*vals: Optional[str]) -> str:
    for v in vals:
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _coalesce_dash(*vals: Optional[str]) -> str:
    v = _coalesce(*vals)
    return v if v else _DASH


def _build_mc_link(message_id: str | None) -> str | None:
    if not message_id:
        return None
    mid = message_id.strip()
    if not re.match(r"^MC\d+$", mid, re.IGNORECASE):
        return None
    # Admin center deep link (works for signed-in admins)
    return f"https://admin.microsoft.com/adminportal/home#/MessageCenter/{mid}"


def _products_pills(product_workload: str) -> str:
    tokens = [t.strip() for t in re.split(r"[\/,|]+", product_workload) if t.strip()]
    if not tokens:
        return ""
    # Render as lightweight “pills” using markdown code span
    return " ".join(f"`{t}`" for t in tokens)


def _to_feature(row: dict[str, str]) -> FeatureRecord:
    # Normalize keys first
    norm: dict[str, str] = {}
    for k, v in row.items():
        if k is None:
            continue
        key = HEADER_ALIASES.get(k.strip().lower(), k.strip())
        norm[key] = v

    # Coalesce values safely
    return FeatureRecord(
        public_id=_coalesce(norm.get("PublicId")),
        title=_coalesce(norm.get("Title")),
        source=_coalesce(norm.get("Source")),
        product=_coalesce(norm.get("Product_Workload")),
        status=_coalesce(norm.get("Status")),
        last_modified=_coalesce(norm.get("LastModified")),
        release_date=_coalesce(norm.get("ReleaseDate")),
        clouds=_coalesce(norm.get("Cloud_instance")),
        roadmap_link=_coalesce(norm.get("Official_Roadmap_link")),
        message_id=_coalesce(norm.get("MessageId")),
    )


def _synthesize_stub(public_id: str) -> FeatureRecord:
    rid = public_id.strip()
    roadmap_url = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}"
    return FeatureRecord(
        public_id=rid,
        title=f"[{rid}]",
        source="seed",
        product="",
        status="",
        last_modified="",
        release_date="",
        clouds="",
        roadmap_link=roadmap_url,
        message_id="",
    )


def _read_master_csv(path: Path) -> list[FeatureRecord]:
    rows: list[FeatureRecord] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append(_to_feature({k or "": (v or "") for k, v in raw.items()}))
    return rows


def _filter_by_cloud(rows: list[FeatureRecord], clouds: list[str]) -> list[FeatureRecord]:
    if not clouds:
        return rows
    selected: set[str] = normalize_clouds(clouds)  # canonical labels (e.g., {'General','GCC'})
    out: list[FeatureRecord] = []
    for r in rows:
        c_raw = (r.clouds or "").strip()
        if not c_raw:
            # If no cloud listed, let it pass (not to accidentally hide items)
            out.append(r)
            continue
        canon = normalize_clouds([c_raw])
        if canon & selected:
            out.append(r)
    return out


def _filter_by_products(rows: list[FeatureRecord], products_filter: str) -> list[FeatureRecord]:
    tokens = [t.lower() for t in _split_csv_like(products_filter)]
    if not tokens:
        return rows
    out: list[FeatureRecord] = []
    for r in rows:
        hay = (r.product or "").lower()
        if any(tok in hay for tok in tokens):
            out.append(r)
    return out


def _cloud_display(selected_clouds: list[str]) -> str:
    if not selected_clouds:
        return "General"
    canon = normalize_clouds(selected_clouds)
    # CLOUD_LABELS maps canonical -> display; keep stable order by this tuple
    order = ("General", "GCC", "GCC High", "DoD")
    display: list[str] = [CLOUD_LABELS.get(c, c) for c in order if c in canon]
    if not display:
        display = sorted(canon)
    return ", ".join(display)


def _toc(entries: list[tuple[str, str]]) -> str:
    # entries: [(anchor, title), ...]
    if not entries:
        return ""
    lines = ["", "## Contents", ""]
    for anchor, title in entries:
        lines.append(f"- [{title}](#{anchor})")
    lines.append("")
    return "\n".join(lines)


def _render_section_block(r: FeatureRecord) -> str:
    """
    Pretty section for each feature. Title bold, Roadmap link inline,
    Message Center ID hyperlinked, summary sources include both.
    """
    title = (r.title or f"[{r.public_id}]").strip()
    anchor = _slugify(title)
    roadmap = r.roadmap_link or (f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={r.public_id}" if r.public_id else "")
    mc_link = _build_mc_link(r.message_id)
    products_row = _products_pills(r.product or "")

    # Header line with bold title; make whole title a link to the roadmap if present
    title_md = f"**{title}**"
    if roadmap:
        title_md = f"**[{title}]({roadmap})**"

    # Small “status/release/clouds” pill row right under title
    status = _coalesce_dash(r.status)
    release = _coalesce_dash(r.release_date)
    clouds = _coalesce_dash(r.clouds)

    top_meta = f"**Status:** {status} &nbsp;&nbsp; **Release:** {release} &nbsp;&nbsp; **Clouds:** {clouds}"
    if products_row:
        top_meta = f"{top_meta}\n\n{products_row}"

    # Compact info table
    msg_id_cell = mc_text = _DASH
    if r.message_id:
        mc_text = r.message_id
        if mc_link:
            msg_id_cell = f"[{r.message_id}]({mc_link})"
        else:
            msg_id_cell = r.message_id

    table = [
        "",
        "<div class=\"feature-card\">",
        f"### <a id=\"{anchor}\"></a> {title_md}",
        "",
        top_meta,
        "",
        "| Roadmap ID | Product / Workload | Last Modified | Source | Message ID |",
        "|---:|---|---|---|---|",
        f"| { _coalesce_dash(r.public_id) } | { _coalesce_dash(r.product) } | { _coalesce_dash(r.last_modified) } | { _coalesce_dash(r.source) } | { msg_id_cell } |",
        "",
        "#### Summary",
    ]

    # Summary text (placeholder today). Include both sources inline.
    sources_bits = []
    if roadmap:
        sources_bits.append(f"[Official Roadmap]({roadmap})")
    if mc_link:
        sources_bits.append(f"[Message Center]({mc_link})")
    sources_line = ""
    if sources_bits:
        sources_line = f"\n\n*Sources:* " + " | ".join(sources_bits)

    table.append("*summary pending*")
    table.append(sources_line or "")

    # Standard sections (placeholders for now)
    table += [
        "",
        "#### ▼ What’s changing",
        "*details pending*",
        "",
        "#### ▼ Impact and rollout",
        "*impact pending*",
        "",
        "#### ▼ Action items",
        "*actions pending*",
        "",
        "</div>",
        "",
        "---",
        "",
    ]
    return "\n".join([line for line in table if line is not None])


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate roadmap markdown from master CSV")
    p.add_argument("--title", required=True, help="Title for the report")
    p.add_argument("--master", required=True, help="Path to *_master.csv from fetch step")
    p.add_argument("--out", required=True, help="Output markdown file path")
    p.add_argument("--since", default="", help="Optional since (YYYY-MM-DD) – informational")
    p.add_argument("--months", default="", help="Optional months window – informational")
    p.add_argument("--cloud", action="append", default=[], help="Cloud filter; may be repeated")
    p.add_argument("--products", default="", help="Comma/pipe-separated product/workload filter; blank = all")
    p.add_argument("--forced-ids", default="", help="Comma-separated exact PublicId list to force/include (ordered)")
    p.add_argument("--no-ai", action="store_true", help="Disable AI deep dive sections (keep placeholders)")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    master_path = Path(args.master)

    # Read input
    rows = _read_master_csv(master_path)
    print(f"[gen] read={len(rows)} from {master_path}")

    # Filter by cloud
    rows = _filter_by_cloud(rows, args.cloud or [])
    print(f"[gen] after cloud filter ({args.cloud or ['General']}): {len(rows)}")

    # Filter by products
    rows = _filter_by_products(rows, args.products or "")
    print(f"[gen] after products filter ({args.products or 'ALL'}): {len(rows)}")

    # Apply forced IDs (ordered), synthesizing stubs if needed
    forced_ids = _split_csv_like(args.forced_ids)
    id_to_row: dict[str, FeatureRecord] = {r.public_id: r for r in rows if r.public_id}
    ordered: list[FeatureRecord] = []
    seen: set[str] = set()

    for fid in forced_ids:
        rec = id_to_row.get(fid) or _synthesize_stub(fid)
        ordered.append(rec)
        seen.add(rec.public_id)

    # Append the rest that weren’t forced
    for r in rows:
        if r.public_id and r.public_id in seen:
            continue
        ordered.append(r)

    rows = ordered
    print(f"[gen] final row count: {len(rows)}")

    # Build the markdown
    generated = datetime.utcnow().replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = _cloud_display(args.cloud or ["General"])

    parts: list[str] = []
    parts.append(
        render_header(
            title=args.title,
            generated_utc=generated,
            cloud_display=cloud_display,
            total_features=len(rows),
        )
    )

    # Mini ToC
    toc_entries: list[tuple[str, str]] = []
    for r in rows:
        t = (r.title or f"[{r.public_id}]").strip()
        toc_entries.append((_slugify(t), t))
    parts.append(_toc(toc_entries))

    # Sections
    for r in rows:
        parts.append(_render_section_block(r))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")

    print(f"Wrote report: {out_path} (features={len(rows)})")


if __name__ == "__main__":
    main()
