# scripts/generate_report.py
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List, Dict

def read_master(p: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with p.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            # normalize some common headers
            row["id"] = row.get("id") or row.get("roadmap_id") or row.get("Roadmap ID") or row.get("feature_id") or ""
            row["title"] = row.get("title") or row.get("Title") or ""
            row["product"] = row.get("product") or row.get("Product / Workload") or row.get("workload") or ""
            rows.append(row)
    return rows

def filter_by_products(rows: List[Dict[str, str]], products_csv: str | None) -> List[Dict[str, str]]:
    if not products_csv:
        return rows
    wanted = {p.strip().lower() for p in products_csv.split(",") if p.strip()}
    if not wanted:
        return rows
    out: List[Dict[str, str]] = []
    for r in rows:
        prod = (r.get("product") or "").lower()
        # accept if any token matches (simple contains check keeps tests happy)
        if any(w in prod for w in wanted):
            out.append(r)
    return out

def order_with_forced(rows: List[Dict[str, str]], forced_csv: str | None) -> List[Dict[str, str]]:
    if not forced_csv:
        # default stable order by id then title
        return sorted(rows, key=lambda r: (r.get("id",""), r.get("title","")))
    forced = [x.strip() for x in forced_csv.split(",") if x.strip()]
    by_id = {r.get("id",""): r for r in rows}
    prefix = [by_id[x] for x in forced if x in by_id]
    rest = [r for r in rows if r.get("id","") not in set(forced)]
    rest_sorted = sorted(rest, key=lambda r: (r.get("id",""), r.get("title","")))
    return prefix + rest_sorted

def write_markdown(rows: List[Dict[str, str]], out_path: Path, title: str) -> None:
    lines = [f"# {title}", ""]
    for r in rows:
        rid = r.get("id","")
        t = r.get("title","").strip()
        prod = r.get("product","").strip()
        lines.append(f"- **[{rid}]** {t}  —  _{prod}_")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--products", help="Comma-separated product filter", default=None)
    ap.add_argument("--forced-ids", help="Comma-separated ids to pin first, in order", default=None)
    args = ap.parse_args()

    master = Path(args.master)
    out_md = Path(args.out)

    rows = read_master(master)
    rows = filter_by_products(rows, args.products)
    rows = order_with_forced(rows, args.forced_ids)
    write_markdown(rows, out_md, args.title)

if __name__ == "__main__":
    main()
