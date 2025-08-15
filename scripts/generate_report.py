from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import Any, cast

CLOUD_MAP = {
    "general": "General",
    "worldwide": "General",
    "worldwide (standard multi-tenant)": "General",
    "gcc": "GCC",
    "gcch": "GCC High",
    "gcc high": "GCC High",
    "dod": "DoD",
}


def normalize_clouds(cloud: str) -> str:
    return CLOUD_MAP.get(cloud.strip().lower(), cloud.strip())


def parse_products_arg(products: str | None) -> set[str]:
    if not products:
        return set()
    parts = [p.strip() for p in products.replace(",", ";").split(";") if p.strip()]
    return {p.lower() for p in parts}


class FeatureRecord(dict[str, Any]):
    pass


def load_master(path: Path) -> list[FeatureRecord]:
    rows: list[FeatureRecord] = []
    with path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for rec in r:
            rows.append(cast(FeatureRecord, rec))
    return rows


def dedupe_keep_latest(items: list[FeatureRecord]) -> list[FeatureRecord]:
    by_id: dict[str, FeatureRecord] = {}
    for it in items:
        pid = (it.get("PublicId") or "").strip()
        if not pid:
            continue
        prev = by_id.get(pid)
        if not prev:
            by_id[pid] = it
            continue
        if (it.get("LastModified") or "") > (prev.get("LastModified") or ""):
            by_id[pid] = it
    return list(by_id.values())


def filter_by_cloud(items: list[FeatureRecord], selected: set[str]) -> list[FeatureRecord]:
    if not selected:
        return items
    out: list[FeatureRecord] = []
    for it in items:
        clouds = {
            normalize_clouds(c)
            for c in (it.get("Cloud_instance") or "").replace(",", ";").split(";")
            if c.strip()
        }
        if clouds & selected:
            out.append(it)
    return out


def filter_by_products(items: list[FeatureRecord], wanted: set[str]) -> list[FeatureRecord]:
    if not wanted:
        return items
    out: list[FeatureRecord] = []
    for it in items:
        prod = (it.get("Product_Workload") or "").lower()
        if any(w in prod for w in wanted):
            out.append(it)
    return out


def render_feature_markdown(r: FeatureRecord) -> str:
    rid = r.get("PublicId", "").strip()
    title = r.get("Title", "").strip()
    product = r.get("Product_Workload", "").strip()
    status = r.get("Status", "").strip() or "—"
    clouds = r.get("Cloud_instance", "").strip() or "—"
    last_mod = r.get("LastModified", "").strip() or "—"
    rel = r.get("ReleaseDate", "").strip() or "—"
    src = r.get("Source", "").strip() or "—"
    msg_id = r.get("MessageId", "").strip() or "—"
    link = r.get("Official_Roadmap_link", "").strip()

    header = f"[{rid}] {title}\n"
    meta = (
        f"Product/Workload: {product} "
        f"Status: {status} "
        f"Cloud(s): {clouds} "
        f"Last Modified: {last_mod} "
        f"Release Date: {rel} "
        f"Source: {src} "
        f"Message ID: {msg_id} "
        f"Official Roadmap: {link}\n"
    )
    body = (
        "\n"
        "Summary\n(summary pending)\n\n"
        "What’s changing\n(details pending)\n\n"
        "Impact and rollout\n(impact pending)\n\n"
        "Action items\n(actions pending)\n\n"
    )
    return header + meta + body


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="Master CSV from fetch step")
    p.add_argument("--out", required=True, help="Markdown output file")
    p.add_argument("--since", default=None, help="YYYY-MM-DD (optional)")
    p.add_argument("--months", type=int, default=None, help="Limit to last N months")
    p.add_argument("--cloud", action="append", help="Cloud filter(s), repeatable")
    p.add_argument("--products", help="CSV/semicolon list of product/workload names to include")
    p.add_argument("--no-window", action="store_true", help="(ignored, compatibility)")
    args = p.parse_args(argv)

    master = Path(args.master)
    out = Path(args.out)
    now = dt.datetime.now(dt.UTC)

    selected: set[str] = set()
    for c in args.cloud or []:
        selected.add(normalize_clouds(c))

    wanted_products = parse_products_arg(args.products)

    rows = load_master(master)
    rows = dedupe_keep_latest(rows)
    rows = filter_by_cloud(rows, selected)
    rows = filter_by_products(rows, wanted_products)

    # Optional date windowing on LastModified
    if args.since or args.months:
        filtered: list[FeatureRecord] = []
        since_dt = None
        if args.since:
            since_dt = dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.UTC)
        for r in rows:
            lm = (r.get("LastModified") or "").strip()
            if not lm:
                filtered.append(r)
                continue
            try:
                d = dt.datetime.fromisoformat(lm.replace("Z", "+00:00"))
            except Exception:
                d = None
            keep = True
            if since_dt and d and d < since_dt:
                keep = False
            if args.months is not None and d:
                cutoff = now - dt.timedelta(days=args.months * 30)
                if d < cutoff:
                    keep = False
            if keep:
                filtered.append(r)
        rows = filtered

    out.parent.mkdir(parents=True, exist_ok=True)
    generated = now.strftime("%Y-%m-%d %H:%M UTC")
    cloud_line = ", ".join(sorted(selected)) if selected else "General"
    prod_line = ", ".join(sorted(wanted_products)) if wanted_products else "All products"
    header = f"Roadmap Report\nGenerated {generated} Cloud filter: {cloud_line} | Products: {prod_line}\n\n"
    body_parts = [render_feature_markdown(r) for r in rows]
    md = (
        f"Generated {generated}\n"
        + header
        + f"Total features: {len(rows)}\n\n"
        + "\n".join(body_parts)
    )
    out.write_text(md, encoding="utf-8")
    print(f"Wrote report: {out} (features={len(rows)})")


if __name__ == "__main__":
    main()
