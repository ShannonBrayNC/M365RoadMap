#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate a markdown roadmap report from a master CSV produced by fetch_messages_graph.py.

Key features:
- Cloud filtering (multi-flag) using canonical labels (General/GCC/GCCH/DoD)
- Product/workload filtering via --products (comma/pipe tokens; blank → all)
- Forced IDs via --forced-ids (ensures rows exist & appear first, in that exact order)
- Mini table of contents and "Products" pill row
- Clean, timezone-aware UTC timestamp

Expected CSV headers (case-sensitive):
PublicId,Title,Source,Product_Workload,Status,LastModified,ReleaseDate,Cloud_instance,Official_Roadmap_link,MessageId
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Iterable, Sequence

# Flexible import of templates (repo-local or "scripts." when invoked from root)
try:
    from report_templates import (  # type: ignore
        CLOUD_LABELS,
        normalize_clouds,
        render_header,
        render_products_row,
        render_toc,
        render_feature_section,
    )
except Exception:  # pragma: no cover
    from scripts.report_templates import (  # type: ignore[no-redef]
        CLOUD_LABELS,
        normalize_clouds,
        render_header,
        render_products_row,
        render_toc,
        render_feature_section,
    )


# ---------- Time helpers (no deprecation warnings) ----------

def _now_utc_str() -> str:
    """UTC timestamp as 'YYYY-MM-DD HH:MM UTC' (timezone-aware)."""
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


# ---------- IO ----------

FIELD_ORDER = [
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


def _read_master_csv(path: str | Path) -> list[dict]:
    """Load rows as dictionaries, preserving expected field names."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Master CSV not found: {p}")
    rows: list[dict] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            r = {k: (raw.get(k, "") or "").strip() for k in FIELD_ORDER}
            rows.append(r)
    print(f"[gen] read={len(rows)} from {p}")
    return rows


def _write_markdown(path: str | Path, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"Wrote report: {p} (features={content.count('### <a id=')})")


# ---------- Filters & helpers ----------

def _split_tokens(s: str | None) -> list[str]:
    if not s:
        return []
    # Split on comma or pipe, trim, drop blanks
    raw = [t.strip() for part in s.split("|") for t in part.split(",")]
    return [t for t in raw if t]


def _filter_by_cloud(rows: Sequence[dict], clouds: Sequence[str] | None) -> list[dict]:
    """
    Keep rows whose Cloud_instance intersects requested canonical clouds.
    If no clouds provided, default to General (match legacy behavior in the workflow).
    """
    requested = normalize_clouds(clouds or ["General"])
    out: list[dict] = []
    for r in rows:
        c = (r.get("Cloud_instance") or "").strip()
        canon = normalize_clouds([s.strip() for s in c.split(",") if s.strip()])
        # If a row has no cloud labels, let it pass only if we asked for "General"
        if not canon and "General" in requested:
            out.append(r)
            continue
        if requested & canon:
            out.append(r)
    print(f"[gen] after cloud filter ({sorted(requested)}): {len(out)}")
    return out


def _filter_by_products(rows: Sequence[dict], products_arg: str | None) -> list[dict]:
    tokens = [t.lower() for t in _split_tokens(products_arg)]
    if not tokens:
        return list(rows)
    out: list[dict] = []
    for r in rows:
        hay = (r.get("Product_Workload") or "").lower()
        if any(tok in hay for tok in tokens):
            out.append(r)
    return out


def _synthesize_row(public_id: str) -> dict:
    """Create a minimal row for a forced PublicId not present in master."""
    pid = public_id.strip()
    return {
        "PublicId": pid,
        "Title": f"[{pid}]",
        "Source": "forced",
        "Product_Workload": "",
        "Status": "",
        "LastModified": "",
        "ReleaseDate": "",
        "Cloud_instance": "",
        "Official_Roadmap_link": f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pid}",
        "MessageId": "",
    }


def _ensure_forced_ids(rows: list[dict], forced_ids: list[str]) -> list[dict]:
    """Guarantee presence & exact ordering of forced IDs, then append others."""
    if not forced_ids:
        return rows

    index: dict[str, dict] = {str(r.get("PublicId", "")).strip(): r for r in rows}
    ordered: list[dict] = []
    seen: set[str] = set()

    for pid in forced_ids:
        pid = pid.strip()
        if not pid:
            continue
        seen.add(pid)
        ordered.append(index.get(pid) or _synthesize_row(pid))

    # Append remaining originals that weren't explicitly forced
    for r in rows:
        pid = str(r.get("PublicId", "")).strip()
        if pid not in seen:
            ordered.append(r)

    return ordered


# ---------- Rendering pipeline ----------

def _cloud_display_from_args(clouds: Sequence[str] | None) -> str:
    if not clouds:
        return "General"
    # Prefer the first provided cloud's canonical label when showing the header,
    # or 'Multiple' if more than one
    canon = list(normalize_clouds(clouds))
    if not canon:
        return "General"
    return canon[0] if len(canon) == 1 else "Multiple"


def _collect_products_set(rows: Sequence[dict]) -> list[str]:
    s: set[str] = set()
    for r in rows:
        val = (r.get("Product_Workload") or "").strip()
        if not val:
            continue
        for token in [t.strip() for t in val.split("/")]:
            if token:
                s.add(token)
    return sorted(s)


def _render_full_report(
    *,
    title: str,
    rows: list[dict],
    clouds_arg: Sequence[str] | None,
    products_arg: str | None,
) -> str:
    parts: list[str] = []
    generated = _now_utc_str()

    cloud_display = _cloud_display_from_args(clouds_arg)
    parts.append(render_header(title=title, generated_utc=generated, cloud_display=cloud_display))

    # Products row: show selected tokens if provided, else all discovered products
    selected_products = _split_tokens(products_arg)
    products_to_show = selected_products or _collect_products_set(rows)
    if products_to_show:
        parts.append(render_products_row(products_to_show))

    # Tiny ToC
    parts.append(render_toc(rows))

    # Feature sections
    for r in rows:
        parts.append(render_feature_section(r))

    return "\n".join(parts).rstrip() + "\n"


# ---------- CLI ----------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate markdown report from master CSV.")
    p.add_argument("--title", required=True, help="Report title, used in header.")
    p.add_argument("--master", required=True, help="Path to master CSV.")
    p.add_argument("--out", required=True, help="Path to output markdown file.")
    p.add_argument("--since", help="Only include items on/after YYYY-MM-DD.", default="")
    p.add_argument("--months", help="Only include items within the last N months.", default="")
    p.add_argument(
        "--cloud",
        action="append",
        help='Cloud label (repeatable). Examples: "Worldwide (Standard Multi-Tenant)", "GCC", "GCC High", "DoD".',
    )
    p.add_argument(
        "--products",
        help="Comma/pipe separated filter for Product/Workload. Blank → all.",
        default="",
    )
    p.add_argument(
        "--forced-ids",
        help="Comma/pipe/space separated exact PublicIds to force/include and order first.",
        default="",
    )
    return p


def main() -> None:
    ap = _build_arg_parser()
    args = ap.parse_args()

    all_rows = _read_master_csv(args.master)

    # Cloud filter
    rows = _filter_by_cloud(all_rows, args.cloud)

    # (Optional) date windowing could be added here in the future using args.since/months

    # Products filter
    rows = _filter_by_products(rows, args.products)

    # Forced IDs
    forced_ids = _split_tokens(args.forced_ids) or []
    if forced_ids:
        rows = _ensure_forced_ids(rows, forced_ids)

    print(f"[gen] final row count: {len(rows)}")

    md = _render_full_report(
        title=args.title,
        rows=rows,
        clouds_arg=args.cloud,
        products_arg=args.products,
    )
    _write_markdown(args.out, md)


if __name__ == "__main__":
    main()
