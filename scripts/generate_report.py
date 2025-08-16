#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a markdown report from a master CSV produced by fetch_messages_graph.py.

Key features:
- Filters by --since / --months (soft date parsing).
- Filters by one or more --cloud values (blank/None treated as "General").
- Filters by --products (comma/pipe/space separated, case-insensitive substring).
- Supports --forced-ids: will (1) include these first in the exact order given,
  and (2) synthesize missing rows so the report is never empty when you force IDs.
- Header uses 'cloud_display' and prints Total features.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import re

# ------------------------------
# Constants / Canonical clouds
# ------------------------------

CLOUD_LABELS: Dict[str, str] = {
    "GENERAL": "General",  # i.e., Worldwide (Standard Multi-Tenant)
    "GCC": "GCC",
    "GCC HIGH": "GCC High",
    "DOD": "DoD",
}

WORLDWIDE_ALIASES: Tuple[str, ...] = (
    "worldwide (standard multi-tenant)",
    "worldwide",
    "standard",
    "general",
    "",
)

CSV_HEADERS: List[str] = [
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

# ------------------------------
# Types
# ------------------------------


@dataclass
class FeatureRecord:
    PublicId: str
    Title: str
    Source: str
    Product_Workload: str
    Status: str
    LastModified: str
    ReleaseDate: str
    Cloud_instance: str
    Official_Roadmap_link: str
    MessageId: str


# ------------------------------
# Helpers
# ------------------------------

def parse_date_soft(s: Optional[str]) -> Optional[str]:
    """Accepts many common date forms; returns ISO YYYY-MM-DD or None."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    fmts = (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%m/%d/%Y",
        "%a, %d %b %Y %H:%M:%S %Z",  # common RSS pubDate
    )
    for f in fmts:
        try:
            d = dt.datetime.strptime(s, f)
            return d.date().isoformat()
        except Exception:
            continue
    return s


def normalize_clouds(value: Optional[str]) -> Set[str]:
    """
    Normalize a free-form cloud string to canonical labels.
    Blank/None -> {"General"} (Worldwide)
    """
    if value is None:
        return {CLOUD_LABELS["GENERAL"]}
    v = value.strip()
    if not v:
        return {CLOUD_LABELS["GENERAL"]}

    lower = v.lower()
    if lower in WORLDWIDE_ALIASES:
        return {CLOUD_LABELS["GENERAL"]}

    tokens = re.split(r"[;,/|]+", lower)
    out: Set[str] = set()
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if t in WORLDWIDE_ALIASES:
            out.add(CLOUD_LABELS["GENERAL"])
        elif t == "gcc":
            out.add(CLOUD_LABELS["GCC"])
        elif t in ("gcch", "gcc high", "gcc-high", "gcc_high"):
            out.add(CLOUD_LABELS["GCC HIGH"])
        elif t in ("dod", "us dod"):
            out.add(CLOUD_LABELS["DOD"])
        else:
            out.add(t.title())

    if not out:
        out.add(CLOUD_LABELS["GENERAL"])
    return out


def include_by_cloud(row_cloud_field: Optional[str], selected: Sequence[str] | Set[str]) -> bool:
    """
    Decide if a row belongs given the selected cloud set/list.
    - selected empty => include all
    - blank row cloud => treat as General
    """
    sel: Set[str] = set(selected) if not isinstance(selected, set) else selected
    if not sel:
        return True
    row_set = normalize_clouds(row_cloud_field)
    return bool(row_set & sel)


def parse_forced_ids(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[,\|\s]+", raw.strip())
    return [p for p in (x.strip() for x in parts) if p]


def parse_products(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[,\|\s]+", raw.strip())
    return [p.lower() for p in (x.strip() for x in parts) if p]


# ------------------------------
# IO
# ------------------------------

def read_master_csv(path: str) -> List[FeatureRecord]:
    out: List[FeatureRecord] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        # normalize header keys (case-insensitive)
        for row in r:
            def g(key: str) -> str:
                # pull case-insensitive with safe default
                for k in row.keys():
                    if k.lower() == key.lower():
                        return str(row[k] or "").strip()
                return ""

            out.append(
                FeatureRecord(
                    PublicId=g("PublicId"),
                    Title=g("Title"),
                    Source=g("Source"),
                    Product_Workload=g("Product_Workload"),
                    Status=g("Status"),
                    LastModified=g("LastModified"),
                    ReleaseDate=g("ReleaseDate"),
                    Cloud_instance=g("Cloud_instance"),
                    Official_Roadmap_link=g("Official_Roadmap_link"),
                    MessageId=g("MessageId"),
                )
            )
    return out


# ------------------------------
# Synthesis for missing forced IDs
# ------------------------------

def synthesize_feature(public_id: str) -> FeatureRecord:
    link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}"
    return FeatureRecord(
        PublicId=public_id,
        Title=f"[{public_id}]",
        Source="seed",
        Product_Workload="",
        Status="",
        LastModified="",
        ReleaseDate="",
        Cloud_instance="",
        Official_Roadmap_link=link,
        MessageId="",
    )


# ------------------------------
# Rendering
# ------------------------------

def _dash_if_empty(s: str) -> str:
    return s if s else "—"


def render_header(*, title: str, generated_utc: str, cloud_display: str, total_features: int) -> str:
    return (
        f"{title}\n"
        f"Generated {generated_utc} Cloud filter: {cloud_display}\n\n"
        f"Total features: {total_features}\n"
    )


def render_feature_markdown(fr: FeatureRecord) -> str:
    """
    Render one feature section, matching the existing style in your sample.
    """
    rid = fr.PublicId or "—"
    title = fr.Title or f"[{rid}]"
    product = _dash_if_empty(fr.Product_Workload)
    status = _dash_if_empty(fr.Status)
    clouds = _dash_if_empty(", ".join(sorted(normalize_clouds(fr.Cloud_instance))) if fr.Cloud_instance != "" else "—")
    lm = _dash_if_empty(parse_date_soft(fr.LastModified) or fr.LastModified)
    rd = _dash_if_empty(parse_date_soft(fr.ReleaseDate) or fr.ReleaseDate)
    src = fr.Source or "—"
    msgid = _dash_if_empty(fr.MessageId)
    link = fr.Official_Roadmap_link or f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}"

    lines = []
    lines.append(f"[{rid}] {title}")
    lines.append(
        f"Product/Workload: {product} "
        f"Status: {status} "
        f"Cloud(s): {clouds} "
        f"Last Modified: {lm} "
        f"Release Date: {rd} "
        f"Source: {src} "
        f"Message ID: {msgid} "
        f"Official Roadmap: {link}"
    )
    lines.append("")  # spacer
    lines.append("Summary")
    lines.append("(summary pending)")
    lines.append("")
    lines.append("What’s changing")
    lines.append("(details pending)")
    lines.append("")
    lines.append("Impact and rollout")
    lines.append("(impact pending)")
    lines.append("")
    lines.append("Action items")
    lines.append("(actions pending)")
    lines.append("")
    return "\n".join(lines)


# ------------------------------
# Filtering & ordering
# ------------------------------

def filter_by_date(rows: List[FeatureRecord], since: Optional[str], months: Optional[int]) -> List[FeatureRecord]:
    out = rows
    if since:
        try:
            cutoff = dt.date.fromisoformat(since).isoformat()
            out = [r for r in out if (parse_date_soft(r.LastModified) or "") >= cutoff]
        except Exception:
            pass
    if months:
        try:
            today = dt.date.today()
            delta_days = months * 30
            cutoff2 = (today - dt.timedelta(days=delta_days)).isoformat()
            out = [r for r in out if (parse_date_soft(r.LastModified) or "") >= cutoff2]
        except Exception:
            pass
    return out


def filter_by_cloud(rows: List[FeatureRecord], selected: Sequence[str] | Set[str]) -> List[FeatureRecord]:
    sel: Set[str] = set(selected) if not isinstance(selected, set) else selected
    if not sel:
        return rows
    return [r for r in rows if include_by_cloud(r.Cloud_instance, sel)]


def filter_by_products(rows: List[FeatureRecord], products_raw: Optional[str]) -> List[FeatureRecord]:
    tokens = parse_products(products_raw)
    if not tokens:
        return rows
    out: List[FeatureRecord] = []
    for r in rows:
        p = (r.Product_Workload or "").lower()
        if any(tok in p for tok in tokens):
            out.append(r)
    return out


def order_with_forced(rows: List[FeatureRecord], forced_ids: List[str]) -> List[FeatureRecord]:
    by_id: Dict[str, FeatureRecord] = {r.PublicId: r for r in rows if r.PublicId}
    ordered: List[FeatureRecord] = []

    # 1) forced first, in order (skip dups)
    seen: Set[str] = set()
    for fid in forced_ids:
        if fid in seen:
            continue
        seen.add(fid)
        fr = by_id.get(fid)
        if fr is None:
            fr = synthesize_feature(fid)
        ordered.append(fr)

    # 2) then everything else not already emitted
    for r in rows:
        if r.PublicId and r.PublicId in seen:
            continue
        ordered.append(r)

    return ordered


# ------------------------------
# CLI
# ------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate markdown report from master CSV.")
    p.add_argument("--title", required=True, help="Report title and artifact base name.")
    p.add_argument("--master", required=True, help="Path to the master CSV.")
    p.add_argument("--out", required=True, help="Markdown output path.")

    p.add_argument("--since", default=None, help="Only include items on/after this date (YYYY-MM-DD).")
    p.add_argument("--months", type=int, default=None, help="Only include items modified within the last N months.")

    p.add_argument(
        "--cloud",
        action="append",
        default=[],
        help='Cloud filter(s). Examples: "Worldwide (Standard Multi-Tenant)", "GCC", "GCC High", "DoD". Can be repeated.',
    )
    p.add_argument("--products", default=None, help="Comma/pipe/space-separated product filter (case-insensitive).")
    p.add_argument("--forced-ids", default=None, help="Comma/pipe/space-separated exact ID list to force/include first.")
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()

    # Read master
    rows = read_master_csv(args.master)

    # Filters
    rows = filter_by_date(rows, args.since, args.months)

    # Cloud selected → canonicalize to set
    selected_clouds: Set[str] = set()
    for c in args.cloud or []:
        selected_clouds |= normalize_clouds(c)

    rows = filter_by_cloud(rows, selected_clouds)
    rows = filter_by_products(rows, args.products)

    # Forced IDs (include/order + synthesize if missing)
    forced_ids = parse_forced_ids(args.forced_ids)
    if forced_ids:
        rows = order_with_forced(rows, forced_ids)

    # Header bits
    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    if not selected_clouds:
        cloud_display = "All clouds"
    else:
        cloud_display = ", ".join(sorted(selected_clouds))

    total = len(rows)

    # Render
    parts: List[str] = [
        render_header(
            title=args.title,
            generated_utc=generated,
            cloud_display=cloud_display,
            total_features=total,
        )
    ]
    for r in rows:
        parts.append(render_feature_markdown(r))

    out_text = "\n".join(parts)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out_text)

    print(f"Wrote report: {args.out} (features={total})")


if __name__ == "__main__":
    main()
