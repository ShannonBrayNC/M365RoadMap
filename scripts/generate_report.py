#!/usr/bin/env python3
"""
Generate a Markdown roadmap report from a master CSV that contains Microsoft 365
message center / roadmap rows.

Key additions in this version:
- --products: comma/pipe list to include only matching Product_Workload rows
- --forced-ids: comma/pipe list of exact PublicIds to pin to the top, keeping the
  exact order provided
- Safer cloud filtering with proper set handling (fixes set |= str errors)
- Clean typing; resolves previous mypy complaints for this file
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

# ---- Local import bootstrap -------------------------------------------------
# We try both "report_templates" and "scripts.report_templates".
# If neither is importable, we fall back to tiny local renderers so the script
# still produces a report rather than crashing.
try:
    from report_templates import (  # type: ignore[import-not-found]
        FeatureRecord,
        render_feature_markdown,
        render_header,
    )
except Exception:  # pragma: no cover - fallback path
    try:
        from scripts.report_templates import (  # type: ignore[import-not-found]
            FeatureRecord,
            render_feature_markdown,
            render_header,
        )
    except Exception:
        # ---- Minimal fallbacks so the report can still be generated ----------
        from dataclasses import dataclass

        @dataclass
        class FeatureRecord:  # type: ignore[override]
            public_id: str
            title: str
            product_workload: str
            status: str
            cloud_instance: str
            last_modified: str
            release_date: str
            source: str
            message_id: str
            official_roadmap_link: str

        def render_header(*, title: str, generated_utc: str, cloud_label: str) -> str:
            return (
                f"{title}\n"
                f"Generated {generated_utc} Cloud filter: {cloud_label or '—'}\n\n"
            )

        def render_feature_markdown(rec: FeatureRecord) -> str:
            lines = [
                f"[{rec.public_id}] {rec.title}",
                f"Product/Workload: {rec.product_workload} "
                f"Status: {rec.status or '—'} "
                f"Cloud(s): {rec.cloud_instance or '—'} "
                f"Last Modified: {rec.last_modified or '—'} "
                f"Release Date: {rec.release_date or '—'} "
                f"Source: {rec.source or '—'} "
                f"Message ID: {rec.message_id or '—'} "
                f"Official Roadmap: {rec.official_roadmap_link or '—'}",
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


# ---- Utilities --------------------------------------------------------------


def _as_set(val: Optional[Iterable[str] | str]) -> set[str]:
    """Normalize a str / Iterable[str] / None into set[str]."""
    if val is None:
        return set()
    if isinstance(val, str):
        v = val.strip()
        return {v} if v else set()
    return {s.strip() for s in val if isinstance(s, str) and s.strip()}


def _split_list(s: Optional[str]) -> list[str]:
    """Split comma/pipe separated string into a clean list (original case)."""
    if not s:
        return []
    parts = re.split(r"[,\|]", s)
    return [p.strip() for p in parts if p.strip()]


# Canonical cloud labels used across the project
_CLOUD_CANON = {
    "GENERAL": "General",
    "WORLDWIDE (STANDARD MULTI-TENANT)": "General",
    "GCC": "GCC",
    "GCC HIGH": "GCC High",
    "DOD": "DoD",
}


def normalize_clouds(value: str | Iterable[str]) -> set[str]:
    """
    Convert a raw cloud label(s) into a canonical set:
    {"General", "GCC", "GCC High", "DoD"}.
    Accepts a single string (optionally comma/pipe separated) or an iterable.
    """
    tokens: list[str]
    if isinstance(value, str):
        tokens = _split_list(value) or [value]
    else:
        tokens = []
        for v in value:
            tokens.extend(_split_list(v) or [v])

    result: set[str] = set()
    for t in tokens:
        key = t.strip().upper()
        if not key:
            continue
        canon = _CLOUD_CANON.get(key)
        if canon:
            result.add(canon)
        else:
            # Keep unknowns verbatim (title-case) so nothing is silently dropped
            result.add(t.strip())
    return result


def _filter_by_products(rows: list[dict[str, str]], products: Optional[Sequence[str]]) -> list[dict[str, str]]:
    """
    Keep rows whose Product_Workload contains ANY of the requested product keywords.
    `products` may be None or a sequence of strings; blank means 'no filter'.
    """
    wanted = {p.lower() for p in (products or []) if p}
    if not wanted:
        return rows

    def matches(row: dict[str, str]) -> bool:
        hay = (row.get("Product_Workload") or "").lower()
        return any(p in hay for p in wanted)

    return [r for r in rows if matches(r)]


def _filter_by_cloud(rows: list[dict[str, str]], cloud: Optional[str]) -> list[dict[str, str]]:
    """
    Keep rows whose Cloud_instance (or Cloud(s)) intersects requested clouds.
    `cloud` may be a single label or a comma/pipe list.
    """
    if not cloud:
        return rows

    requested: set[str] = set()
    for tok in _split_list(cloud):
        requested |= normalize_clouds(tok)

    if not requested:
        return rows

    def row_clouds(r: dict[str, str]) -> set[str]:
        raw = r.get("Cloud_instance") or r.get("Cloud(s)") or ""
        return normalize_clouds(raw)

    return [r for r in rows if row_clouds(r) & requested]


def _parse_forced_ids(s: Optional[str]) -> list[str]:
    """Return ordered list of forced PublicIds from a comma/pipe separated string."""
    return _split_list(s)


def _order_by_forced_ids(rows: list[dict[str, str]], forced_ids: list[str]) -> list[dict[str, str]]:
    """
    Place any rows whose PublicId matches one of forced_ids (string match) at the top,
    preserving the exact order of forced_ids. The rest follow in original order.
    """
    if not forced_ids:
        return rows

    by_id: dict[str, dict[str, str]] = {}
    for r in rows:
        pid = (r.get("PublicId") or "").strip()
        if pid and pid not in by_id:
            by_id[pid] = r

    ordered: list[dict[str, str]] = [by_id[fid] for fid in forced_ids if fid in by_id]

    picked = set(id(x) for x in ordered)
    for r in rows:
        if id(r) not in picked:
            ordered.append(r)
    return ordered


def _within_window(
    value_iso: str,
    *,
    since_iso: Optional[str],
    months: Optional[int],
    now: Optional[dt.datetime] = None,
) -> bool:
    """
    Return True if the given ISO date string (YYYY-MM-DD or ISO-ish) is within
    the requested window (since OR months). If neither filter provided, always True.
    """
    if not since_iso and not months:
        return True

    # Try parsing date; if it fails, we keep the row (fail-open).
    try:
        # Accept 'YYYY-MM-DD' or broader ISO
        if len(value_iso) >= 10:
            value = dt.datetime.fromisoformat(value_iso[:10])
        else:
            return True
    except Exception:
        return True

    if since_iso:
        try:
            since = dt.datetime.fromisoformat(since_iso[:10])
        except Exception:
            since = None
        if since and value < since:
            return False

    if months:
        ref = (now or dt.datetime.utcnow())
        # naive month window: months * ~30 days
        cutoff = ref - dt.timedelta(days=30 * months)
        if value < cutoff:
            return False

    return True


def _filter_by_time_window(
    rows: list[dict[str, str]],
    *,
    since: Optional[str],
    months: Optional[int],
) -> list[dict[str, str]]:
    if not since and not months:
        return rows

    out: list[dict[str, str]] = []
    now = dt.datetime.utcnow()
    for r in rows:
        # Prefer LastModified; fall back to ReleaseDate
        lm = (r.get("LastModified") or "").strip()
        rd = (r.get("ReleaseDate") or "").strip()
        date_str = lm or rd
        if not date_str:
            out.append(r)
            continue
        if _within_window(date_str, since_iso=since, months=months, now=now):
            out.append(r)
    return out


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict({k: (v or "") for k, v in row.items()}) for row in reader]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="CSV with master rows")
    p.add_argument("--out", required=True, help="Output markdown path")
    p.add_argument("--since")
    p.add_argument("--months", type=int)
    p.add_argument("--cloud", help='e.g. "Worldwide (Standard Multi-Tenant)", or "GCC|DoD"')
    p.add_argument(
        "--products",
        help="Comma/pipe-separated list of product keywords to include (e.g., 'Intune,Teams|SharePoint')",
    )
    p.add_argument(
        "--forced-ids",
        help="Comma/pipe-separated list of PublicIds to force to the top (exact order preserved).",
    )
    p.add_argument("--no-window", action="store_true", help="Ignore time window filters")
    return p.parse_args()


# ---- Main -------------------------------------------------------------------


def main() -> None:
    args = _parse_args()

    rows = _read_rows(Path(args.master))

    # Time window
    if not args.no_window:
        rows = _filter_by_time_window(rows, since=args.since, months=args.months)

    # Cloud filter
    rows = _filter_by_cloud(rows, args.cloud)

    # Product filter
    products_list = _split_list(args.products)
    rows = _filter_by_products(rows, products_list)

    # Forced IDs ordering (exact-ID, exact ordering)
    forced_ids = _parse_forced_ids(args.forced_ids)
    rows = _order_by_forced_ids(rows, forced_ids)

    # Build MD
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cloud_label = ", ".join(sorted(normalize_clouds(args.cloud))) if args.cloud else ""
    parts: list[str] = [render_header(title=args.title, generated_utc=generated, cloud_label=cloud_label)]

    count = 0
    for r in rows:
        rec = FeatureRecord(
            public_id=(r.get("PublicId") or "").strip(),
            title=(r.get("Title") or "").strip(),
            product_workload=(r.get("Product_Workload") or "").strip(),
            status=(r.get("Status") or "").strip(),
            cloud_instance=(r.get("Cloud_instance") or "").strip(),
            last_modified=(r.get("LastModified") or "").strip(),
            release_date=(r.get("ReleaseDate") or "").strip(),
            source=(r.get("Source") or "").strip(),
            message_id=(r.get("MessageId") or "").strip(),
            official_roadmap_link=(r.get("Official_Roadmap_link") or "").strip(),
        )
        parts.append(render_feature_markdown(rec))
        count += 1

    md = "".join(parts)
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote report: {out_path} (features={count})")


if __name__ == "__main__":
    main()
