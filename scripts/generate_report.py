#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Local UI helpers (same folder)
from report_templates import (
    render_header,
    render_toc,
    render_feature_card,
)

# ---- CSV schema we expect (kept stable with your pipeline)
CSV_FIELDS = [
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
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="master CSV path")
    p.add_argument("--out", required=True, help="output markdown path")
    p.add_argument("--since", default="")
    p.add_argument("--months", default="")
    p.add_argument("--cloud", action="append", default=[], help="filter by cloud(s)")
    p.add_argument("--products", default="", help="comma/pipe/space separated product/workload filters")
    p.add_argument("--forced-ids", default="", help="comma/pipe/space separated Ids; synthesize any missing")
    return p.parse_args(argv)


def _read_master_csv(path: str | Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for raw in r:
            row = {k: (raw.get(k) or "").strip() for k in CSV_FIELDS}
            rows.append(row)
    return rows


def _split_list(s: str) -> List[str]:
    if not s:
        return []
    parts = re.split(r"[,\s|]+", s.strip())
    return [p for p in parts if p]


def _filter_by_cloud(rows: List[Dict[str, str]], clouds: List[str]) -> List[Dict[str, str]]:
    if not clouds:
        return rows
    want = {c.strip().lower() for c in clouds if c.strip()}
    out: List[Dict[str, str]] = []
    for r in rows:
        c = (r.get("Cloud_instance") or "").strip().lower()
        if not c:
            # treat blank as General, accepted if 'general' is requested
            if "general" in want or "worldwide (standard multi-tenant)" in want:
                out.append(r)
        else:
            # allow substring match (e.g., "GCC" within "GCC High")
            if any(w in c for w in want):
                out.append(r)
    return out


def _filter_by_products(rows: List[Dict[str, str]], prods: str) -> List[Dict[str, str]]:
    filters = [p.lower() for p in _split_list(prods)]
    if not filters:
        return rows
    out: List[Dict[str, str]] = []
    for r in rows:
        pw = (r.get("Product_Workload") or "").lower()
        if any(f in pw for f in filters):
            out.append(r)
    return out


def _synthesize_missing(forced_ids: List[str], rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    have = {r.get("PublicId", "") for r in rows if r.get("PublicId")}
    out = rows[:]
    for fid in forced_ids:
        if fid not in have:
            out.append({
                "PublicId": fid,
                "Title": f"[{fid}]",
                "Source": "seed",
                "Product_Workload": "",
                "Status": "",
                "LastModified": "",
                "ReleaseDate": "",
                "Cloud_instance": "",
                "Official_Roadmap_link": f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={fid}",
                "MessageId": "",
            })
    return out


def _sort_rows(rows: List[Dict[str, str]], forced_ids: List[str]) -> List[Dict[str, str]]:
    # Forced IDs first (given order), then rest by LastModified desc
    rank: Dict[str, int] = {fid: i for i, fid in enumerate(forced_ids)}

    def key(r: Dict[str, str]) -> Tuple[int, str]:
        pid = r.get("PublicId", "")
        forced_ord = rank.get(pid, 10_000 + (hash(pid) & 0xFFFF))
        lm = r.get("LastModified", "")
        try:
            iso = datetime.fromisoformat(lm.replace("Z", "+00:00")).isoformat()
        except Exception:
            iso = ""
        return (forced_ord, iso)

    return sorted(rows, key=key, reverse=True)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    all_rows = _read_master_csv(args.master)
    print(f"[gen] read={len(all_rows)} from {args.master}")

    # Filters
    rows = _filter_by_cloud(all_rows, args.cloud or ["General"])
    print(f"[gen] after cloud filter ({args.cloud or ['General']}): {len(rows)}")
    rows = _filter_by_products(rows, args.products)

    # Forced/synthetic
    forced_ids = _split_list(args.forced_ids)
    rows = _synthesize_missing(forced_ids, rows)
    rows = _sort_rows(rows, forced_ids)
    print(f"[gen] final row count: {len(rows)}")

    # Header + ToC
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cloud_display = ", ".join(args.cloud or ["General"])
    parts: List[str] = []
    parts.append(render_header(title=args.title, generated_utc=generated, cloud_display=cloud_display))
    parts.append(render_toc(rows))

    # Feature cards
    for r in rows:
        parts.append(render_feature_card(r))

    out = "\n\n".join(parts).strip() + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(out, encoding="utf-8")
    print(f"Wrote report: {args.out} (features={len(rows)})")


if __name__ == "__main__":
    main()
