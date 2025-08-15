#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import textwrap
from collections.abc import Iterable
from pathlib import Path

import pandas as pd


def _pick(cols: Iterable[str], *candidates: str) -> str | None:
    cl = [c.lower() for c in cols]
    for cand in candidates:
        if cand in cols:
            return cand
        # case-insensitive / contains
        for i, c in enumerate(cl):
            if cand.lower() == c:
                return list(cols)[i]
    # fuzzy contains for common fields
    for cand in candidates:
        for i, c in enumerate(cl):
            if cand.lower() in c:
                return list(cols)[i]
    return None


def _load_csv_maybe(p: str | None) -> pd.DataFrame | None:
    if not p:
        return None
    fp = Path(p)
    if not fp.exists():
        return None
    try:
        return pd.read_csv(fp)
    except Exception:
        # try parquet if someone passed it
        if fp.suffix.lower() in {".parquet", ".pq"}:
            return pd.read_parquet(fp)
        raise


def _nice_date(s: str) -> str:
    try:
        return pd.to_datetime(s, utc=True).strftime("%Y-%m-%d")
    except Exception:
        return s


def build_report(
    title: str,
    master_csv: str,
    graph_csv: str | None,
    since: str | None,
    months: int | None,
    tenant_cloud: str | None,
) -> str:
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    master = pd.read_csv(master_csv)
    graph = _load_csv_maybe(graph_csv)

    cols = list(master.columns)
    id_col = _pick(
        cols, "Id", "FeatureID", "Feature Id", "feature_id", "MessageId", "messageId", "PublicId"
    )
    title_col = _pick(cols, "Title", "title", "MessageTitle")
    service_col = _pick(cols, "Service", "Services", "Product", "Workload", "Category")
    status_col = _pick(cols, "Status", "State", "classification")
    lm_col = _pick(
        cols,
        "LastModified",
        "LastModifiedDateTime",
        "lastModifiedDateTime",
        "Modified",
        "ChangedDate",
    )
    rel_col = _pick(cols, "ReleaseDate", "StartDate", "releaseDate", "startDate", "ETA")

    # summary counts
    total = len(master)
    by_source = {}
    src_col = _pick(cols, "Source", "source")
    if src_col:
        by_source = master[src_col].value_counts().to_dict()

    # top services
    top_services_md = ""
    if service_col:
        svc = (
            master[service_col]
            .fillna("Unspecified")
            .astype(str)
            .str.split(";|,")
            .explode()
            .str.strip()
        )
        top = svc.value_counts().head(10)
        if not top.empty:
            top_services_md = "\n".join(f"| {k} | {v} |" for k, v in top.items())

    # recent changes
    recent_md = ""
    if lm_col and title_col:
        tmp = master[[c for c in [lm_col, title_col, id_col, service_col, status_col] if c]].copy()
        tmp[lm_col] = pd.to_datetime(tmp[lm_col], errors="coerce", utc=True)
        tmp = tmp.sort_values(lm_col, ascending=False).head(20)
        if not tmp.empty:
            rows = []
            for _, r in tmp.iterrows():
                rid = str(r.get(id_col, "") or "")
                rows.append(
                    f"| {_nice_date(str(r[lm_col]))} | {str(r[title_col])[:80]} "
                    f"| {rid} | {str(r.get(service_col,''))[:24]} | {str(r.get(status_col,''))[:16]} |"
                )
            recent_md = "\n".join(rows)

    # upcoming (if date present)
    upcoming_md = ""
    if rel_col and title_col:
        tmp = master[[c for c in [rel_col, title_col, id_col, service_col, status_col] if c]].copy()
        tmp[rel_col] = pd.to_datetime(tmp[rel_col], errors="coerce", utc=True)
        future = tmp[tmp[rel_col] >= pd.Timestamp.utcnow()].sort_values(rel_col).head(20)
        if not future.empty:
            rows = []
            for _, r in future.iterrows():
                rid = str(r.get(id_col, "") or "")
                rows.append(
                    f"| {_nice_date(str(r[rel_col]))} | {str(r[title_col])[:80]} "
                    f"| {rid} | {str(r.get(service_col,''))[:24]} | {str(r.get(status_col,''))[:16]} |"
                )
            upcoming_md = "\n".join(rows)

    # optional graph stats
    graph_count = len(graph) if graph is not None else 0

    hdr = textwrap.dedent(f"""\
    # {title}

    _Generated {now}_

    **Window**: {'since ' + since if since else (str(months)+' months' if months else 'n/a')}
    **Tenant cloud filter**: {tenant_cloud or 'none'}

    **Totals**: {total:,} items
    **By source**: {', '.join(f"{k}={v}" for k,v in by_source.items()) if by_source else 'n/a'}
    **Graph items**: {graph_count:,}
    """)

    body = [hdr]

    if top_services_md:
        body.append(
            textwrap.dedent("""\
            ## Top services/products
            | Service | Items |
            |---|---|
            """)
            + top_services_md
            + "\n"
        )

    if recent_md:
        body.append(
            textwrap.dedent("""\
            ## Most recently updated (20)
            | Last Modified | Title | ID | Service | Status |
            |---|---|---|---|---|
            """)
            + recent_md
            + "\n"
        )

    if upcoming_md:
        body.append(
            textwrap.dedent("""\
            ## Upcoming items (20)
            | Release Date | Title | ID | Service | Status |
            |---|---|---|---|---|
            """)
            + upcoming_md
            + "\n"
        )

    if not (top_services_md or recent_md or upcoming_md):
        body.append("\n_No recognizable columns to summarize. The CSV schema may have changed._\n")

    return "\n".join(body)


def main():
    ap = argparse.ArgumentParser(description="Generate Markdown roadmap report from CSVs")
    ap.add_argument("--title", default=os.environ.get("TITLE", "roadmap_report"))
    ap.add_argument("--master", required=True, help="Path to master.csv (combined output)")
    ap.add_argument("--graph", help="Path to graph_messages_master.csv (optional)")
    ap.add_argument("--since", default=os.environ.get("SINCE", ""))
    ap.add_argument("--months", type=int, default=int(os.environ.get("MONTHS", "0") or 0))
    ap.add_argument("--tenant-cloud", default=os.environ.get("TENANT_CLOUD", ""))
    ap.add_argument("--out", required=True, help="Path to write the Markdown report")
    args = ap.parse_args()

    md = build_report(
        args.title,
        args.master,
        args.graph,
        args.since or None,
        args.months or None,
        args.tenant_cloud,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(md, encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    sys.exit(main())
