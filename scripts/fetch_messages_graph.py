# scripts/fetch_messages_graph.py  (top of file)

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html  # ← add this
import json
import re  # ← and this
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence, Set, TypedDict, Tuple, Iterable

try:
    import requests  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

# Prefer the real client; if unavailable, keep the script runnable.
try:
    from scripts.graph_client import GraphClient, GraphConfig  # type: ignore[import-not-found]
except Exception:  # pragma: no cover

    class GraphClient:  # minimal protocol
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        def fetch_messages(self) -> list[dict[str, Any]]:
            return []

    class GraphConfig(dict):  # type: ignore[type-arg]
        ...


# ----------------------------- Types exported to tests ------------------------


class Row(TypedDict, total=False):
    public_id: str | None
    title: str
    source: str
    product: str | None
    status: str | None
    last_modified: str | None
    release_date: str | None
    clouds: set[str]
    official_roadmap: str | None
    message_id: str | None


__all__ = [
    "Row",
    "merge_sources",
    "transform_graph_messages",
    "transform_public_items",
    "transform_rss",
    "include_by_cloud",
    "extract_clouds",
    "normalize_clouds",
    "fetch_public_json",
    "fetch_rss",
]


# --------------------------------- Clouds ------------------------------------

_CLOUD_MAP = {
    "general": "General",
    "worldwide": "General",
    "worldwide (standard multi-tenant)": "General",
    "gcc": "GCC",
    "gcch": "GCC High",
    "gcc high": "GCC High",
    "dod": "DoD",
}


def normalize_clouds(value: str | Iterable[str]) -> set[str]:
    """Accept a string or list; return normalized cloud labels."""
    values = [value] if isinstance(value, str) else list(value)
    out: set[str] = set()
    for v in values:
        key = v.strip().lower()
        out.add(_CLOUD_MAP.get(key, v.strip()))
    return out


def extract_clouds(cloud_field: str | None) -> set[str]:
    return {c.strip() for c in re.split(r"[;,]", cloud_field or "") if c.strip()}


def include_by_cloud(cloud_field: str, selected: Iterable[str]) -> bool:
    """
    Returns True if any item cloud is in selected. Accepts list/set for 'selected'
    to play nicely with tests and callers.
    """
    selected_set = set(selected)
    if not selected_set:
        return True
    item = extract_clouds(cloud_field)
    return bool(item & selected_set)


# -------------------------------- Products -----------------------------------


def parse_products_arg(products: str | None) -> set[str]:
    """
    Parse --products comma/semicolon string into a lowercase set.
    Blank/None => empty set (means 'no filter').
    """
    if not products:
        return set()
    parts = [p.strip() for p in re.split(r"[;,]", products) if p.strip()]
    return {p.lower() for p in parts}


def include_by_product(product_field: str | None, wanted: Iterable[str]) -> bool:
    """
    True if the product/workload matches any of 'wanted' (case-insensitive).
    If 'wanted' is empty => allow all.
    """
    wanted_set = {w.lower() for w in wanted}
    if not wanted_set:
        return True
    txt = (product_field or "").lower()
    # simple contains check — keeps it forgiving (e.g., "Microsoft Teams" matches "teams")
    return any(w in txt for w in wanted_set)


# ----------------------------- Transform helpers -----------------------------


def transform_graph_messages(
    items: list[dict[str, Any]], selected_clouds: Iterable[str], wanted_products: Iterable[str]
) -> list[Row]:
    rows: list[Row] = []
    selected_clouds = set(selected_clouds)
    for it in items:
        clouds = extract_clouds(it.get("clouds") or it.get("cloud") or "")
        if selected_clouds and not (clouds & selected_clouds):
            continue
        product = it.get("product") or it.get("product_workload") or ""
        if not include_by_product(product, wanted_products):
            continue
        rows.append(
            Row(
                public_id=str(it.get("roadmapId") or it.get("id") or ""),
                title=str(it.get("title") or ""),
                source="graph",
                product=product,
                status=it.get("status") or "",
                last_modified=str(it.get("lastModified") or it.get("last_modified") or ""),
                release_date=str(it.get("releaseDate") or it.get("release_date") or ""),
                clouds=clouds,
                official_roadmap=it.get("official_roadmap") or "",
                message_id=str(it.get("messageId") or it.get("message_id") or ""),
            )
        )
    return rows


def transform_public_items(
    items: list[dict[str, Any]], selected_clouds: Iterable[str], wanted_products: Iterable[str]
) -> list[Row]:
    rows: list[Row] = []
    selected_clouds = set(selected_clouds)
    for it in items:
        clouds = extract_clouds(it.get("clouds") or "")
        if selected_clouds and not (clouds & selected_clouds):
            continue
        product = it.get("product") or ""
        if not include_by_product(product, wanted_products):
            continue
        rows.append(
            Row(
                public_id=str(it.get("id") or ""),
                title=str(it.get("title") or ""),
                source="public-json",
                product=product,
                status=it.get("status") or "",
                last_modified=str(it.get("lastModified") or ""),
                release_date=str(it.get("releaseDate") or ""),
                clouds=clouds,
                official_roadmap=it.get("link") or "",
                message_id="",
            )
        )
    return rows


_RE_RSS_ITEM = re.compile(r"<item\b.*?>.*?</item>", re.I | re.S)
_RE_TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_RE_LINK = re.compile(r"<link>(.*?)</link>", re.I | re.S)
_RE_PUBDATE = re.compile(r"<pubDate>(.*?)</pubDate>", re.I | re.S)


def _clean_xml_text(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", s or "").strip())


def transform_rss(xml_text: str, wanted_products: Iterable[str]) -> list[Row]:
    """Very small RSS parser; treat each item as Windows/roadmap news."""
    rows: list[Row] = []
    for m in _RE_RSS_ITEM.finditer(xml_text or ""):
        block = m.group(0)
        title = _clean_xml_text(next(iter(_RE_TITLE.findall(block)), ""))
        link = _clean_xml_text(next(iter(_RE_LINK.findall(block)), ""))
        pub = _clean_xml_text(next(iter(_RE_PUBDATE.findall(block)), ""))
        # basic product include check against title text
        if not include_by_product(title, wanted_products):
            continue
        rows.append(
            Row(
                public_id="",
                title=title,
                source="rss",
                product="",
                status="",
                last_modified=pub,
                release_date="",
                clouds=set(),
                official_roadmap=link,
                message_id="",
            )
        )
    return rows


def merge_sources(*groups: list[Row]) -> list[Row]:
    out: list[Row] = []
    for g in groups:
        out.extend(g)
    return out


# ---------------------------------- Fetch ------------------------------------


def _load_config(path: str | None) -> GraphConfig:
    if not path:
        return GraphConfig()
    p = Path(path)
    if not p.exists():
        return GraphConfig()
    return GraphConfig(json.loads(p.read_text(encoding="utf-8")))


def _fetch_graph(cfg: GraphConfig, no_window: bool) -> list[dict[str, Any]]:
    """
    Use the real Graph client if available; if it raises or requests is missing,
    return [] so callers can fall back.
    """
    try:
        client = GraphClient(cfg, no_window=no_window)  # type: ignore[call-arg]
        return client.fetch_messages()
    except Exception:
        return []


def fetch_public_json() -> list[dict[str, Any]]:
    """Project-specific public JSON; keep failure-safe."""
    return []


def fetch_rss() -> str:
    """Optional RSS feed for additional context."""
    return ""


# ---------------------------------- Output -----------------------------------

_HEADERS = [
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


def _rows_to_csv(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(_HEADERS)
        for r in rows:
            clouds_str = "; ".join(sorted(r.get("clouds", set()))) if r.get("clouds") else ""
            w.writerow(
                [
                    r.get("public_id", "") or "",
                    r.get("title", "") or "",
                    r.get("source", "") or "",
                    r.get("product", "") or "",
                    r.get("status", "") or "",
                    r.get("last_modified", "") or "",
                    r.get("release_date", "") or "",
                    clouds_str,
                    r.get("official_roadmap", "") or "",
                    r.get("message_id", "") or "",
                ]
            )


def _rows_to_json(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("clouds"), set):
            d["clouds"] = sorted(d["clouds"])
        serializable.append(d)
    path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")


# ----------------------------------- CLI -------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="Path to Graph config JSON.")
    p.add_argument("--cloud", dest="clouds", action="append", help="Cloud filters (repeatable).")
    p.add_argument("--products", help="CSV/semicolon list of product/workload names to include.")
    p.add_argument(
        "--no-window", action="store_true", help="Avoid interactive browser if possible."
    )
    p.add_argument(
        "--essentials-only", action="store_true", help="Disable AI deep dive (Graph only)."
    )
    p.add_argument("--emit", choices=["csv", "json"], required=True, help="Emit CSV or JSON.")
    p.add_argument("--out", required=True, help="Output file path.")
    p.add_argument("--stats-out", help="Optional stats JSON path.")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    selected_clouds: set[str] = set()
    if args.clouds:
        for c in args.clouds:
            selected_clouds |= normalize_clouds(c)

    wanted_products = parse_products_arg(args.products)

    cfg = _load_config(args.config)
    graph_raw = _fetch_graph(cfg, no_window=args.no_window)

    # Deep dive (default ON): include RSS + public in addition to Graph.
    do_deep = not args.essentials_only
    public_raw: list[dict[str, Any]] = fetch_public_json() if do_deep else []
    rss_text: str = fetch_rss() if do_deep else ""

    graph_rows = transform_graph_messages(graph_raw, selected_clouds, wanted_products)
    public_rows = transform_public_items(public_raw, selected_clouds, wanted_products)
    rss_rows = transform_rss(rss_text, wanted_products)

    rows = merge_sources(graph_rows, public_rows, rss_rows)

    out_path = Path(args.out)
    if args.emit == "csv":
        _rows_to_csv(rows, out_path)
    else:
        _rows_to_json(rows, out_path)

    if args.stats_out:
        stats = {
            "generated": dt.datetime.now(dt.UTC).isoformat(),
            "counts": {
                "graph-raw": len(graph_raw),
                "public-json": len(public_raw),
                "rss-raw": 1 if rss_text else 0,
                "graph": len(graph_rows),
                "public": len(public_rows),
                "rss": len(rss_rows),
            },
            "cloud_selected": sorted(selected_clouds),
            "products_selected": sorted(wanted_products),
            "deep": do_deep,
        }
        Path(args.stats_out).write_text(json.dumps(stats, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
