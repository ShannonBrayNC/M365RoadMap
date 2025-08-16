#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

# Optional deps
try:
    import msal  # type: ignore
    HAVE_MSAL = True
except Exception:
    HAVE_MSAL = False

# ---------- Models ----------


@dataclass
class Row:
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

    @staticmethod
    def headers() -> list[str]:
        return [
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


# ---------- Helpers ----------


def _now_utc_iso() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_csv_like(s: str | None) -> list[str]:
    if not s:
        return []
    # Split on comma/pipe/whitespace, keep order
    parts = re.split(r"[,\|\s]+", s.strip())
    return [p for p in parts if p]


def _normalize_cloud_label(label: str) -> str:
    lab = label.strip().lower()
    if "dod" in lab:
        return "DoD"
    if "high" in lab:
        return "GCC High"
    if "gcc" in lab:
        return "GCC"
    if "worldwide" in lab or "general" in lab or "multi-tenant" in lab:
        return "General"
    # fallback – pass-through title case
    return label.strip() or "General"


def _include_by_cloud(rec: Row, selected: set[str]) -> bool:
    if not selected:
        return True
    c = _normalize_cloud_label(rec.Cloud_instance or "")
    return c in selected


def _seed_rows_from_ids(ids: list[str], source: str = "seed") -> list[Row]:
    out: list[Row] = []
    for i in ids:
        pid = i.strip()
        if not pid:
            continue
        out.append(
            Row(
                PublicId=pid,
                Title=f"[{pid}]",
                Source=source,
                Product_Workload="",
                Status="",
                LastModified="",
                ReleaseDate="",
                Cloud_instance="",
                Official_Roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pid}",
                MessageId="",
            )
        )
    return out


def write_csv(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=Row.headers())
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def write_json(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = [{k: asdict(r).get(k, "") for k in Row.headers()} for r in rows]
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_config(path: Optional[str]) -> dict:
    cfg_path = Path(path or "graph_config.json")
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _graph_ready(cfg: dict) -> bool:
    # Light check for creds present
    return (
        HAVE_MSAL
        and bool(cfg.get("TENANT"))
        and bool(cfg.get("CLIENT"))
        and bool(cfg.get("PFX_B64"))
        and ("M365_PFX_PASSWORD" in os.environ or cfg.get("M365_PFX_PASSWORD"))
    )


# ---------- Graph (stub/optional) ----------


def _try_fetch_graph(cfg: dict, clouds: set[str], since: str | None, months: str | None) -> tuple[list[Row], Optional[str]]:
    """
    Intentionally conservative: if anything looks off, return error (caller falls back).
    This keeps the workflow reliable even without Graph.
    """
    if not _graph_ready(cfg):
        return [], "Graph client not available on this runner"

    # You can wire real calls here later; for now, just indicate we attempted and skip
    return [], "Graph fetch not implemented in this safe build"


# ---------- public JSON / RSS placeholders (no-ops for now) ----------


def _try_public_sources(cfg: dict, clouds: set[str]) -> list[Row]:
    # Placeholders – return empty list; you can drop your parsers in later
    return []


# ---------- CLI ----------


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="graph_config.json")
    p.add_argument("--since", help="YYYY-MM-DD", default="")
    p.add_argument("--months", help="N months window", default="")
    p.add_argument("--cloud", action="append", default=[], help="Repeatable cloud filter")
    p.add_argument("--no-graph", action="store_true")
    p.add_argument("--seed-ids", default="", help="Comma/pipe-separated PublicId seeds")

    p.add_argument("--emit", required=True, choices=["csv", "json"])
    p.add_argument("--out", required=True)
    p.add_argument("--stats-out", default="")
    return p.parse_args(list(argv) if argv is not None else None)


# ---------- MAIN ----------


def main() -> None:
    args = parse_args()

    # Normalize clouds
    selected: set[str] = set()
    for c in args.cloud or []:
        selected.add(_normalize_cloud_label(c))

    cfg = _load_config(args.config)

    # seed
    seeds = _split_csv_like(args.seed_ids)
    seed_rows = _seed_rows_from_ids(seeds) if seeds else []

    stats = {
        "generated_utc": _now_utc_iso(),
        "cloud_filter": sorted(selected) or ["General"],
        "sources": {"graph": 0, "public-json": 0, "rss": 0, "seed": len(seed_rows)},
        "errors": 0,
    }

    all_rows: list[Row] = []

    # Graph first (unless explicitly disabled)
    graph_err: Optional[str] = None
    g_rows: list[Row] = []
    if not args.no_graph:
        g_rows, graph_err = _try_fetch_graph(cfg, selected, args.since, args.months)
        if graph_err:
            print(f"WARN: graph-fetch failed: {graph_err}")
            stats["errors"] += 1
    stats["sources"]["graph"] = len(g_rows)
    all_rows.extend(g_rows)

    # Public sources
    pub_rows = _try_public_sources(cfg, selected)
    stats["sources"]["public-json"] = sum(1 for r in pub_rows if r.Source == "public-json")
    stats["sources"]["rss"] = sum(1 for r in pub_rows if r.Source == "rss")
    all_rows.extend(pub_rows)

    # Seeds last (forcible inclusion)
    all_rows.extend(seed_rows)

    # Cloud filter (defensive)
    if selected:
        all_rows = [r for r in all_rows if _include_by_cloud(r, selected)]

    # De-dup by PublicId, keep first
    seen: set[str] = set()
    deduped: list[Row] = []
    for r in all_rows:
        if r.PublicId and r.PublicId not in seen:
            deduped.append(r)
            seen.add(r.PublicId)

    # Always write outputs and stats, even if empty
    if args.emit == "csv":
        write_csv(args.out, deduped)
        if args.stats_out:
            Path(args.stats_out).write_text(json.dumps(stats, indent=2), encoding="utf-8")
    else:
        write_json(args.out, deduped)
        if args.stats_out:
            Path(args.stats_out).write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(f'Done. rows={len(deduped)} sources={json.dumps(stats["sources"])} errors={stats["errors"]}')
    # Optional debug: list output dir files
    out_dir = Path(args.out).parent
    files = sorted([p.name for p in out_dir.glob("*")])
    print(f"DEBUG: files in {out_dir}: {files}")


if __name__ == "__main__":
    main()
