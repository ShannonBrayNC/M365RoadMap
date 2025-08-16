#!/usr/bin/env python3
"""
generate_report.py
Create a Markdown report from the master CSV produced by fetch_messages_graph.py.

Key features:
- --forced-ids: comma/space separated list of PublicId values to pin at the top (keeps exact order)
- --products:   comma-separated filter for Product/Workload (case-insensitive, substring match)
- --cloud:      may be passed multiple times; accepts friendly “Worldwide (Standard Multi-Tenant)”, GCC, GCC High, DoD
- --since / --months: time window filters (by LastModified); either may be used
- Renders header with cloud_display and total feature count
- Gracefully falls back to local rendering if report_templates is unavailable
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# --- Robust imports for the shared renderer (optional) -----------------------
# If the repo is executed from root, `scripts` may not be on sys.path.
# Try both styles; if they fail, we use simple local renderers.
try:
    from scripts.report_templates import (  # type: ignore
        FeatureRecord,
        render_feature_markdown,
        render_header,
    )
    HAVE_TEMPLATES = True
except Exception:
    try:
        # Try local import relative to this file (when running inside scripts/)
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from report_templates import (  # type: ignore
            FeatureRecord,
            render_feature_markdown,
            render_header,
        )

        HAVE_TEMPLATES = True
    except Exception:
        HAVE_TEMPLATES = False


# --------------------------- Cloud mapping helpers ---------------------------

# Canonical labels we use internally
CANON_CLOUDS = ("General", "GCC", "GCC High", "DoD")

DISPLAY_TO_CANON: Dict[str, str] = {
    "general": "General",
    "worldwide (standard multi-tenant)": "General",
    "worldwide": "General",
    "gcc": "GCC",
    "gcc high": "GCC High",
    "gcch": "GCC High",
    "dod": "DoD",
    "department of defense": "DoD",
}

CANON_TO_DISPLAY: Dict[str, str] = {
    "General": "Worldwide (Standard Multi-Tenant)",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
}


def normalize_cloud_token(token: str) -> Optional[str]:
    t = token.strip().lower()
    return DISPLAY_TO_CANON.get(t, None)


def row_clouds_to_canon(value: str) -> List[str]:
    """
    Normalize a master CSV 'Cloud_instance' field to a list of canonical labels.
    Accepts values such as 'General', 'Worldwide (Standard Multi-Tenant)', 'GCC', 'GCC High', 'DoD',
    possibly combined with commas/semicolons.
    """
    if not value:
        return []
    parts = [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
    out: List[str] = []
    for p in parts:
        canon = normalize_cloud_token(p) or (p if p in CANON_CLOUDS else None)
        if canon and canon not in out:
            out.append(canon)
    return out


def selected_clouds_to_canon(selected: Sequence[str] | None) -> List[str]:
    if not selected:
        return []
    out: List[str] = []
    for s in selected:
        canon = normalize_cloud_token(s) or (s if s in CANON_CLOUDS else None)
        if canon and canon not in out:
            out.append(canon)
    return out


def header_cloud_display(selected_canon: List[str]) -> str:
    if not selected_canon:
        return "All clouds"
    disp = [CANON_TO_DISPLAY.get(c, c) for c in selected_canon]
    return ", ".join(disp)


# ------------------------------- Date helpers --------------------------------

def parse_iso_soft(s: str) -> Optional[dt.datetime]:
    """
    Parse ISO-ish dates like '2025-08-06' or '2025-08-06T19:53:44.487Z'.
    Returns a timezone-aware UTC datetime when possible.
    """
    if not s:
        return None
    s = s.strip()
    try:
        # Handle Z suffix quickly
        if s.endswith("Z"):
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            return d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        # Try date-only
        try:
            d2 = dt.datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
            return d2
        except Exception:
            return None


def cutoff_from_since_or_months(since: Optional[str], months: Optional[int]) -> Optional[dt.datetime]:
    if since:
        d = parse_iso_soft(since)
        return d
    if months:
        # Approximate months as 30 days each to avoid heavy deps
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)
    return None


# ------------------------------ CSV / filtering ------------------------------

Row = Dict[str, str]

MASTER_HEADERS = [
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


def read_master_csv(path: Path) -> List[Row]:
    rows: List[Row] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Normalize missing keys
            for k in MASTER_HEADERS:
                r.setdefault(k, "")
            rows.append(r)
    return rows


def any_product_match(product_field: str, needles: List[str]) -> bool:
    if not needles:
        return True
    hay = product_field.lower()
    return any(n in hay for n in needles)


def filter_rows(
    rows: List[Row],
    cutoff: Optional[dt.datetime],
    selected_clouds_canon: List[str],
    product_terms: List[str],
) -> List[Row]:
    out: List[Row] = []
    for r in rows:
        # Time window by LastModified (if cutoff provided)
        if cutoff:
            lm = parse_iso_soft(r.get("LastModified", ""))
            if not lm or lm < cutoff:
                continue

        # Cloud filter (if set)
        if selected_clouds_canon:
            row_canon = row_clouds_to_canon(r.get("Cloud_instance", ""))
            if not set(selected_clouds_canon).intersection(row_canon):
                continue

        # Product filter
        if not any_product_match(r.get("Product_Workload", ""), product_terms):
            continue

        out.append(r)
    return out


def parse_forced_ids(s: str) -> List[str]:
    """
    Accepts comma/space/semicolon separated list of IDs (strings).
    Keeps order and uniqueness in the order provided.
    """
    if not s:
        return []
    raw = [x.strip() for x in s.replace(";", " ").replace(",", " ").split() if x.strip()]
    out: List[str] = []
    for x in raw:
        if x not in out:
            out.append(x)
    return out


def format_clouds_for_line(value: str) -> str:
    c = row_clouds_to_canon(value)
    if not c:
        return "—"
    return ", ".join(CANON_TO_DISPLAY.get(x, x) for x in c)


# ------------------------------- Rendering -----------------------------------

def local_render_header(title: str, generated_utc: str, cloud_display: str, total_features: int) -> str:
    return (
        f"{title}\n"
        f"Generated {generated_utc} Cloud filter: {cloud_display}\n\n"
        f"Total features: {total_features}\n"
    )


def local_render_feature(r: Row) -> str:
    public_id = r.get("PublicId", "").strip() or "—"
    title = r.get("Title", "").strip() or "—"
    product = r.get("Product_Workload", "").strip() or "—"
    status = r.get("Status", "").strip() or "—"
    clouds = format_clouds_for_line(r.get("Cloud_instance", ""))
    last_mod = (r.get("LastModified", "").strip() or "—").replace("T", " ")
    rel_date = (r.get("ReleaseDate", "").strip() or "—")
    source = r.get("Source", "").strip() or "—"
    mid = r.get("MessageId", "").strip() or "—"
    link = r.get("Official_Roadmap_link", "").strip() or "—"

    lines = [
        f"[{public_id}] {title}",
        (
            f"Product/Workload: {product} "
            f"Status: {status} "
            f"Cloud(s): {clouds} "
            f"Last Modified: {last_mod} "
            f"Release Date: {rel_date} "
            f"Source: {source} "
            f"Message ID: {mid} "
            f"Official Roadmap: {link}"
        ),
        "",
        "Summary",
        "(summary pending)",
        "",
        "What’s changing",
        "(details pending)",
        "",
        "Impact and rollout",
        "(impact pending)",
        "",
        "Action items",
        "(actions pending)",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------- Main -------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True, help="Report title")
    p.add_argument("--master", required=True, help="Path to master CSV")
    p.add_argument("--out", required=True, help="Output Markdown path")
    p.add_argument("--since", help="YYYY-MM-DD (UTC)")
    p.add_argument("--months", type=int, help="Include items modified in the last N months")
    p.add_argument(
        "--cloud",
        action="append",
        help='Repeatable. Examples: "Worldwide (Standard Multi-Tenant)", "GCC", "GCC High", "DoD"',
    )
    p.add_argument(
        "--products",
        help="Comma-separated list of product/workload substrings to include (case-insensitive). Blank = all.",
        default="",
    )
    p.add_argument(
        "--forced-ids",
        help="Comma/space/semicolon-separated list of PublicId values to pin at top in the exact order provided.",
        default="",
    )
    # Keep backward-compatibility; ignored if present
    p.add_argument("--no-window", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)

    master_path = Path(args.master)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows_all = read_master_csv(master_path)

    # Build helpers
    selected_clouds_canon = selected_clouds_to_canon(args.cloud)
    products_terms = [t.strip().lower() for t in args.products.split(",") if t.strip()]
    cutoff = cutoff_from_since_or_months(args.since, args.months)

    # Forced IDs are always included, even if they don’t match filters
    forced_ids = parse_forced_ids(args.forced_ids)
    by_id: Dict[str, Row] = {r.get("PublicId", ""): r for r in rows_all}
    forced_rows: List[Row] = [by_id[i] for i in forced_ids if i in by_id]

    # Apply filters to the rest
    filtered = filter_rows(rows_all, cutoff, selected_clouds_canon, products_terms)

    # Deduplicate: drop any forced rows from filtered remainder
    forced_set = {r.get("PublicId", "") for r in forced_rows}
    remainder = [r for r in filtered if r.get("PublicId", "") not in forced_set]

    final_rows = forced_rows + remainder
    total = len(final_rows)

    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = header_cloud_display(selected_clouds_canon)

    parts: List[str] = []

    if HAVE_TEMPLATES:
        # Use shared templates if available
        header_md = render_header(
            title=args.title,
            generated_utc=generated,
            cloud_display=cloud_display,
            total_features=total,
        )
        parts.append(header_md)

        # Build FeatureRecord objects if the dataclass exists;
        # if the constructor signature differs, fall back to local rendering.
        try:
            recs: List[FeatureRecord] = []
            for r in final_rows:
                recs.append(
                    FeatureRecord(
                        public_id=r.get("PublicId", ""),
                        title=r.get("Title", ""),
                        product=r.get("Product_Workload", ""),
                        status=r.get("Status", ""),
                        clouds=format_clouds_for_line(r.get("Cloud_instance", "")),
                        last_modified=r.get("LastModified", ""),
                        release_date=r.get("ReleaseDate", ""),
                        source=r.get("Source", ""),
                        message_id=r.get("MessageId", ""),
                        roadmap_link=r.get("Official_Roadmap_link", ""),
                    )
                )
            for rec in recs:
                parts.append(render_feature_markdown(rec))
        except Exception:
            # If the dataclass signature mismatches, render locally instead.
            for r in final_rows:
                parts.append(local_render_feature(r))
    else:
        # Local simple rendering
        parts.append(local_render_header(args.title, generated, cloud_display, total))
        for r in final_rows:
            parts.append(local_render_feature(r))

    out_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote report: {out_path} (features={total})")


if __name__ == "__main__":
    main()
