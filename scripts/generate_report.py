#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
import datetime as dt
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Ensure we can import "scripts.*" when run as `python scripts/generate_report.py`
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Prefer absolute, then fallback to relative if someone runs from scripts/
try:
    from scripts.report_templates import (  # type: ignore[attr-defined]
        FeatureRecord,
        render_feature_markdown,
        normalize_clouds,
        parse_date_soft,
        CLOUD_LABELS,
    )
except Exception:  # pragma: no cover - fallback
    from report_templates import (  # type: ignore[no-redef]
        FeatureRecord,
        render_feature_markdown,
        normalize_clouds,
        parse_date_soft,
        CLOUD_LABELS,
    )

CSV_HEADERS = [
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


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate Roadmap Markdown from the master CSV."
    )
    p.add_argument("--title", required=True, help="Report title")
    p.add_argument("--master", required=True, help="Path to master CSV")
    p.add_argument("--out", required=True, help="Output markdown path")
    p.add_argument("--since", help="ISO date (YYYY-MM-DD) lower bound on LastModified")
    p.add_argument(
        "--months",
        type=int,
        help="Lookback window in months (mutually compatible with --since; uses the later bound).",
    )
    p.add_argument(
        "--cloud",
        action="append",
        default=None,
        help='Cloud filter; pass multiple like: --cloud "Worldwide (Standard Multi-Tenant)" --cloud GCC',
    )
    p.add_argument(
        "--products",
        default="",
        help='Comma/space separated product/workload filters (e.g. "Teams, Intune"). Blank = all.',
    )
    p.add_argument(
        "--forced-ids",
        default="",
        help="IDs to include even if other filters would exclude them. "
        "Match against PublicId *or* MessageId. Separate by comma/space/newline. "
        "ORDER IS PRESERVED.",
    )
    return p.parse_args(argv)


def _to_utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load_rows(csv_path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        # Soft validate header presence
        missing = [h for h in CSV_HEADERS if h not in r.fieldnames if r.fieldnames]
        if missing:
            print(f"[generate_report] WARN missing headers: {missing}", file=sys.stderr)
        for row in r:
            rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def _earliest_cutoff(since: Optional[str], months: Optional[int]) -> Optional[dt.date]:
    a: Optional[dt.date] = None
    if since:
        d = parse_date_soft(since)
        if isinstance(d, dt.date):
            a = d
    if months and months > 0:
        today = dt.date.today()
        year = today.year
        month = today.month - months
        while month <= 0:
            month += 12
            year -= 1
        # pick same day-of-month if possible; otherwise clamp
        days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][
            month - 1
        ]
        day = min(today.day, days_in_month)
        b = dt.date(year, month, day)
        a = max(a, b) if a else b
    return a


def _tokenize(s: str) -> List[str]:
    # Unordered tokens (legacy helper)
    raw = [t.strip() for part in s.split(",") for t in part.replace("\n", " ").split(" ")]
    return [t for t in raw if t]


def _tokenize_ordered(s: str) -> List[str]:
    """Split by comma/space/newline, preserve order, drop duplicates."""
    raw = s.replace(",", " ").replace("\n", " ").split()
    out: List[str] = []
    seen: Set[str] = set()
    for t in raw:
        if t and t not in seen:
            out.append(t)
            seen.add(t)
    return out


def _filter_by_cloud(rows: Iterable[Dict[str, str]], clouds: Optional[Sequence[str]]) -> List[Dict[str, str]]:
    if not clouds:
        return list(rows)
    selected: Set[str] = set()
    for c in clouds:
        selected |= normalize_clouds(c)  # returns a set of canonical labels
    out: List[Dict[str, str]] = []
    for r in rows:
        rc = r.get("Cloud_instance", "")
        labels = {lab.strip() for lab in rc.replace(";", ",").split(",") if lab.strip()}
        canon: Set[str] = set()
        for lab in labels:
            canon |= normalize_clouds(lab)
        if not labels:
            # If a row has no cloud label at all, include only if "General" is selected
            if "General" in selected or "Worldwide (Standard Multi-Tenant)" in selected:
                out.append(r)
        elif selected & canon:
            out.append(r)
    return out


def _filter_by_products(rows: Iterable[Dict[str, str]], products: str) -> List[Dict[str, str]]:
    tokens = {t.lower() for t in _tokenize(products)}
    if not tokens:
        return list(rows)
    out: List[Dict[str, str]] = []
    for r in rows:
        blob = f"{r.get('Product_Workload','')} {r.get('Title','')}".lower()
        if any(tok in blob for tok in tokens):
            out.append(r)
    return out


def _filter_by_date(rows: Iterable[Dict[str, str]], cutoff: Optional[dt.date]) -> List[Dict[str, str]]:
    if not cutoff:
        return list(rows)
    out: List[Dict[str, str]] = []
    for r in rows:
        lm = parse_date_soft(r.get("LastModified", ""))
        if isinstance(lm, dt.date) and lm >= cutoff:
            out.append(r)
    return out


def _filter_by_forced_ids(rows: Iterable[Dict[str, str]], forced_ids: str) -> Tuple[List[Dict[str, str]], Set[str]]:
    """
    If --forced-ids provided, return ONLY those rows whose PublicId or MessageId matches,
    ordered exactly by the sequence of tokens provided by the user.
    """
    ordered_tokens = _tokenize_ordered(forced_ids)
    if not ordered_tokens:
        return list(rows), set()

    index_map: Dict[str, int] = {tok: i for i, tok in enumerate(ordered_tokens)}
    hits: Set[str] = set()
    matched: List[Tuple[int, Dict[str, str]]] = []

    for r in rows:
        pub = r.get("PublicId", "")
        msg = r.get("MessageId", "")
        idxs: List[int] = []
        if pub in index_map:
            idxs.append(index_map[pub])
            hits.add(pub)
        if msg in index_map:
            idxs.append(index_map[msg])
            hits.add(msg)
        if idxs:
            matched.append((min(idxs), r))

    matched.sort(key=lambda x: x[0])
    ordered_rows = [r for _, r in matched]
    return ordered_rows, hits


def _dedupe_public_id(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: Set[str] = set()
    out: List[Dict[str, str]] = []
    for r in rows:
        pid = r.get("PublicId", "")
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        out.append(r)
    return out


def _row_to_feature(r: Dict[str, str]) -> FeatureRecord:
    return FeatureRecord(
        public_id=r.get("PublicId", ""),
        title=r.get("Title", ""),
        source=r.get("Source", ""),
        product=r.get("Product_Workload", ""),
        status=r.get("Status", ""),
        last_modified=r.get("LastModified", ""),
        release_date=r.get("ReleaseDate", ""),
        clouds=r.get("Cloud_instance", ""),
        roadmap_link=r.get("Official_Roadmap_link", ""),
        message_id=r.get("MessageId", ""),
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    title: str = args.title
    master = Path(args.master)
    out_md = Path(args.out)

    all_rows = _load_rows(master)

    cutoff = _earliest_cutoff(args.since, args.months)
    rows = _filter_by_date(all_rows, cutoff)
    rows = _filter_by_cloud(rows, args.cloud)
    rows = _filter_by_products(rows, args.products)

    # Preserve the user's explicit order for --forced-ids
    forced_input_order = _tokenize_ordered(args.forced_ids)
    rows, forced_hits = _filter_by_forced_ids(rows, args.forced_ids)

    rows = _dedupe_public_id(rows)
    features = [_row_to_feature(r) for r in rows]

    cloud_display = ", ".join(args.cloud) if args.cloud else "All"
    products_display = args.products if args.products else "All"
    forced_display = ", ".join(forced_input_order) if forced_input_order else "—"

    header = [
        f"# {title}",
        f"Generated {_to_utc_stamp()}",
        f"Cloud filter: {cloud_display}",
        f"Products: {products_display}",
        f"Forced IDs (ordered): {forced_display}",
        "",
        f"Total features: {len(features)}",
        "",
    ]

    body_parts: List[str] = []
    for rec in features:
        body_parts.append(render_feature_markdown(rec))

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(header + body_parts), encoding="utf-8")

    print(f"Wrote report: {out_md} (features={len(features)})", file=sys.stderr)

    # Optional debug stats
    cloud_hist: Dict[str, int] = {"General": 0, "GCC": 0, "GCC High": 0, "DoD": 0}
    for r in rows:
        labs = {lab.strip() for lab in r.get("Cloud_instance", "").replace(";", ",").split(",") if lab.strip()}
        if not labs:
            cloud_hist["General"] += 1
        else:
            for lab in labs:
                for canon in normalize_clouds(lab):
                    if canon in cloud_hist:
                        cloud_hist[canon] += 1
    after_date_cnt = len(_filter_by_date(all_rows, cutoff))
    after_cloud_cnt = len(_filter_by_cloud(_filter_by_date(all_rows, cutoff), args.cloud))
    print(
        f"[generate_report] rows: total={len(all_rows)} after_date={after_date_cnt} "
        f"after_cloud={after_cloud_cnt} after_products={len(rows)} final={len(features)} | cloud_hist={cloud_hist}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
