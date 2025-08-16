#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch Microsoft 365 roadmap/message-center content into a master CSV/JSON.

Key behaviors:
- Tries real Microsoft Graph first (if config/secrets look valid).
- If Graph is missing or fails, automatically falls back to public sources.
- Treats blank/empty Cloud_instance as "General".
- Supports --cloud filters, --since/--months, and emits CSV/JSON.
- Writes and prints fetch stats for easy debugging.
- Accepts list *or* set for cloud selection helpers (keeps tests happy).

This module keeps function names used by existing tests:
- Row (dataclass)
- normalize_clouds
- include_by_cloud
- transform_graph_messages
- transform_public_items
- transform_rss
- merge_sources

NOTE: Public-source functions here are intentionally simple. Wire them to your
project’s actual public RSS/JSON endpoints if needed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Match, Optional, Sequence, Set, Tuple, Union

# Optional imports — keep soft so mypy/tests don’t explode in CI
try:
    import requests  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

# Try to import your Graph client. If unavailable on runner, we’ll fall back.
try:
    from scripts.graph_client import (
        GraphClient,  # type: ignore[import-not-found]
        GraphConfig,  # type: ignore[import-not-found]
        acquire_token,  # type: ignore[import-not-found]
    )
except Exception:  # pragma: no cover
    GraphClient = None  # type: ignore[assignment]
    GraphConfig = None  # type: ignore[assignment]
    acquire_token = None  # type: ignore[assignment]


# ------------------------------
# Constants / Regex
# ------------------------------

# Roadmap ID can be numeric or alphanumeric; keep broad but constrained.
_RE_ROADMAP_ID: re.Pattern[str] = re.compile(r"\[([0-9A-Za-z\-]+)\]")

# Canonical cloud labels used throughout the repo
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

# ------------------------------
# Data model
# ------------------------------


@dataclass
class Row:
    PublicId: str
    Title: str
    Source: str  # "graph", "rss", "public-json", etc.
    Product_Workload: str
    Status: str
    LastModified: str
    ReleaseDate: str
    Cloud_instance: str  # raw input value; blank -> treated as General
    Official_Roadmap_link: str
    MessageId: str

    def to_csv_row(self) -> List[str]:
        return [
            self.PublicId,
            self.Title,
            self.Source,
            self.Product_Workload,
            self.Status,
            self.LastModified,
            self.ReleaseDate,
            self.Cloud_instance,
            self.Official_Roadmap_link,
            self.MessageId,
        ]


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
# Helpers
# ------------------------------

def parse_date_soft(s: Optional[str]) -> Optional[str]:
    """Accepts many common date forms; returns ISO YYYY-MM-DD or None."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # Try several formats commonly seen in feeds or Graph
    fmts = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y")
    for f in fmts:
        try:
            d = dt.datetime.strptime(s, f)
            return d.date().isoformat()
        except Exception:
            continue
    # As a last resort, return original string
    return s


def normalize_clouds(value: str | None) -> Set[str]:
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

    # Split on common separators and normalize tokens
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
            # Unknown => keep verbatim capitalized
            out.add(t.title())

    if not out:
        out.add(CLOUD_LABELS["GENERAL"])
    return out


def include_by_cloud(row_cloud_field: str | None, selected: Union[Sequence[str], Set[str]]) -> bool:
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


def _has_valid_graph_config(cfg: Dict[str, Any]) -> bool:
    """True if config looks usable for cert-based auth."""
    need = ("tenant", "client_id", "pfx_base64", "pfx_password_env")
    return all(bool(cfg.get(k)) for k in need)


def _load_cfg(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _safe_head(seq: Sequence[Any], n: int) -> Sequence[Any]:
    return seq[:n] if len(seq) >= n else seq


# ------------------------------
# Public transforms/fetchers
# ------------------------------

def transform_graph_messages(items: List[Dict[str, Any]]) -> List[Row]:
    """Map Graph API objects into Row."""
    out: List[Row] = []
    for it in items:
        rid = str(it.get("roadmapId") or it.get("PublicId") or it.get("id") or "").strip()
        title = str(it.get("title") or it.get("Title") or "").strip()
        product = str(it.get("product") or it.get("Product_Workload") or "").strip()
        status = str(it.get("status") or it.get("Status") or "").strip()
        lm = parse_date_soft(it.get("lastModified") or it.get("LastModified"))
        rd = parse_date_soft(it.get("releaseDate") or it.get("ReleaseDate"))
        clouds_raw = str(it.get("clouds") or it.get("Cloud_instance") or "").strip()
        link = str(it.get("roadmapLink") or it.get("Official_Roadmap_link") or "").strip()
        msgid = str(it.get("messageId") or it.get("MessageId") or "").strip()

        out.append(
            Row(
                PublicId=rid,
                Title=title,
                Source="graph",
                Product_Workload=product,
                Status=status,
                LastModified=lm or "",
                ReleaseDate=rd or "",
                Cloud_instance=clouds_raw,
                Official_Roadmap_link=link,
                MessageId=msgid,
            )
        )
    return out


def transform_public_items(items: List[Dict[str, Any]]) -> List[Row]:
    """Map public JSON items into Row."""
    out: List[Row] = []
    for it in items:
        rid = str(it.get("PublicId") or it.get("Id") or it.get("id") or "").strip()
        title = str(it.get("Title") or it.get("title") or "").strip()
        product = str(it.get("Product_Workload") or it.get("product") or "").strip()
        status = str(it.get("Status") or it.get("status") or "").strip()
        lm = parse_date_soft(it.get("LastModified") or it.get("lastModified"))
        rd = parse_date_soft(it.get("ReleaseDate") or it.get("releaseDate"))
        clouds_raw = str(it.get("Cloud_instance") or it.get("clouds") or "").strip()
        link = str(it.get("Official_Roadmap_link") or it.get("roadmapLink") or "").strip()
        msgid = str(it.get("MessageId") or it.get("messageId") or "").strip()

        out.append(
            Row(
                PublicId=rid,
                Title=title,
                Source="public-json",
                Product_Workload=product,
                Status=status,
                LastModified=lm or "",
                ReleaseDate=rd or "",
                Cloud_instance=clouds_raw,
                Official_Roadmap_link=link,
                MessageId=msgid,
            )
        )
    return out


def transform_rss(items: List[Dict[str, Any]]) -> List[Row]:
    """Map RSS entries into Row. Expects entries with title/summary/link/updated."""
    out: List[Row] = []
    for it in items:
        title = str(it.get("title") or "").strip()
        m: Optional[Match[str]] = _RE_ROADMAP_ID.search(title)
        rid = m.group(1) if m else ""
        lm = parse_date_soft(it.get("updated") or it.get("published"))
        link = str(it.get("link") or "").strip()

        out.append(
            Row(
                PublicId=rid,
                Title=title,
                Source="rss",
                Product_Workload=str(it.get("product") or ""),
                Status=str(it.get("status") or ""),
                LastModified=lm or "",
                ReleaseDate="",
                Cloud_instance=str(it.get("clouds") or ""),
                Official_Roadmap_link=link,
                MessageId=str(it.get("messageId") or ""),
            )
        )
    return out


def merge_sources(rows: List[Row]) -> List[Row]:
    """
    De-duplicate by PublicId, preferring Graph over others.
    """
    by_id: Dict[str, Row] = {}
    priority = {"graph": 3, "public-json": 2, "rss": 1}
    for r in rows:
        key = r.PublicId or r.MessageId or r.Title
        if not key:
            # fall back to unique-ish
            key = f"{r.Source}:{r.Title}"
        existing = by_id.get(key)
        if not existing or priority.get(r.Source, 0) > priority.get(existing.Source, 0):
            by_id[key] = r
    return list(by_id.values())


# ------------------------------
# Fetchers (Graph + public)
# ------------------------------

def fetch_from_graph(cfg: Dict[str, Any], since: Optional[str], months: Optional[int]) -> List[Row]:
    """
    Use your GraphClient (if available) to fetch roadmap/message-center content.
    If client code is not present, raises RuntimeError to trigger fallback.
    """
    if GraphClient is None or GraphConfig is None or acquire_token is None:
        raise RuntimeError("Graph client not available on this runner")

    # Minimal example — your repo likely has richer logic:
    gcfg = GraphConfig(
        tenant=cfg["tenant"],
        client_id=cfg["client_id"],
        pfx_base64=cfg["pfx_base64"],
        pfx_password_env=cfg["pfx_password_env"],
    )
    token = acquire_token(gcfg)
    client = GraphClient(token)

    # Example endpoint; replace with your actual
    # items = client.list_roadmap_updates(since=since, months=months)
    items: List[Dict[str, Any]] = []  # TODO: integrate your real call
    return transform_graph_messages(items)


def _fetch_public_json(url: Optional[str]) -> List[Dict[str, Any]]:
    if not url or requests is None:
        return []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Allow a top-level "items" array
            items = data.get("items")
            return items if isinstance(items, list) else []
        return []
    except Exception:
        return []


def _fetch_public_rss(url: Optional[str]) -> List[Dict[str, Any]]:
    """
    Very light RSS fetcher. If you have feedparser in requirements you can
    replace this with a proper parse to pull fields you care about.
    """
    if not url or requests is None:
        return []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        # Minimal parse: just split items by <item> boundaries
        text = r.text
        parts = re.split(r"<item\b", text, flags=re.I)
        out: List[Dict[str, Any]] = []
        for p in parts[1:]:
            # naive title/link extraction
            m_title = re.search(r"<title>(.*?)</title>", p, flags=re.I | re.S)
            m_link = re.search(r"<link>(.*?)</link>", p, flags=re.I | re.S)
            m_date = re.search(r"<pubDate>(.*?)</pubDate>", p, flags=re.I | re.S)
            title = (m_title.group(1) if m_title else "").strip()
            link = (m_link.group(1) if m_link else "").strip()
            updated = (m_date.group(1) if m_date else "").strip()
            out.append({"title": title, "link": link, "updated": updated})
        return out
    except Exception:
        return []


def fetch_public_sources(
    cfg: Dict[str, Any],
    since: Optional[str],
    months: Optional[int],
) -> List[Row]:
    """
    Fetch from public JSON+RSS if configured. This keeps placeholders so the
    script produces output even when Graph is unavailable.
    """
    public_json_url = cfg.get("public_json_url")  # Optional
    public_rss_url = cfg.get("public_rss_url")    # Optional

    rows: List[Row] = []

    # Public JSON (if provided)
    json_items = _fetch_public_json(public_json_url)
    if json_items:
        rows.extend(transform_public_items(json_items))

    # Public RSS (if provided)
    rss_items = _fetch_public_rss(public_rss_url)
    if rss_items:
        rows.extend(transform_rss(rss_items))

    return rows


# ------------------------------
# Emitters / CLI
# ------------------------------

def write_emit(rows: List[Row], emit: str, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if emit == "csv":
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(CSV_HEADERS)
            for r in rows:
                w.writerow(r.to_csv_row())
    elif emit == "json":
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)
    else:  # pragma: no cover
        raise ValueError(f"Unknown emit format: {emit}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch roadmap/messages into CSV/JSON with cloud filters.")
    p.add_argument("--config", help="Path to graph_config.json", default=None)
    p.add_argument("--since", help="Only include items on/after this date (YYYY-MM-DD).", default=None)
    p.add_argument("--months", type=int, help="Only include items modified within the last N months.", default=None)
    p.add_argument(
        "--cloud",
        action="append",
        default=[],
        help='Cloud filter(s). Examples: "Worldwide (Standard Multi-Tenant)", "GCC", "GCC High", "DoD". Can be repeated.',
    )
    p.add_argument("--no-graph", action="store_true", help="Skip Graph entirely; use public fallbacks only.")
    p.add_argument("--emit", choices=("csv", "json"), required=True, help="Output format.")
    p.add_argument("--out", required=True, help="Output file path.")
    p.add_argument("--stats-out", help="Optional JSON stats output path.")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    cfg = _load_cfg(args.config)

    # Auto-fallback guard if Graph secrets are missing/invalid
    if not args.no_graph and not _has_valid_graph_config(cfg):
        print("INFO: Graph credentials missing/invalid → using public fallback only (as if --no-graph).")
        args.no_graph = True

    # Compute selected cloud set (canonical)
    selected: Set[str] = set()
    for c in args.cloud or []:
        selected |= normalize_clouds(c)

    all_rows: List[Row] = []
    stats: Dict[str, Any] = {"sources": {"graph": 0, "public-json": 0, "rss": 0}, "errors": 0}

    # Try Graph first (unless disabled)
    if not args.no_graph:
        try:
            g_rows = fetch_from_graph(cfg, args.since, args.months)
            stats["sources"]["graph"] = len(g_rows)
            all_rows.extend(g_rows)
        except Exception as e:  # pragma: no cover (depends on env)
            stats["errors"] = stats.get("errors", 0) + 1
            print(f"WARN: graph-fetch failed: {e}")

    # Always try public sources
    pub_rows = fetch_public_sources(cfg, args.since, args.months)
    # Record counts by their Source as mapped in transforms
    stats["sources"]["public-json"] = sum(1 for r in pub_rows if r.Source == "public-json")
    stats["sources"]["rss"] = sum(1 for r in pub_rows if r.Source == "rss")
    all_rows.extend(pub_rows)

    # Dedupe
    merged = merge_sources(all_rows)

    # Cloud filter (treat blank/None as General)
    if selected:
        merged = [r for r in merged if include_by_cloud(r.Cloud_instance, selected)]

    # Date filters (soft)
    if args.since:
        try:
            cutoff = dt.date.fromisoformat(args.since)
            merged = [r for r in merged if (parse_date_soft(r.LastModified) or "") >= cutoff.isoformat()]
        except Exception:
            pass

    # Months filter: items modified within last N months
    if args.months:
        try:
            today = dt.date.today()
            # Very simple months -> days approximation (30d each); refine if needed
            delta_days = args.months * 30
            cutoff2 = (today - dt.timedelta(days=delta_days)).isoformat()
            merged = [r for r in merged if (parse_date_soft(r.LastModified) or "") >= cutoff2]
        except Exception:
            pass

    # Emit
    write_emit(merged, args.emit, args.out)

    # Stats
    final_count = len(merged)
    stats["final"] = final_count
    print(f"Done. rows={final_count} sources={stats['sources']} errors={stats['errors']}")

    if args.stats_out:
        try:
            os.makedirs(os.path.dirname(args.stats_out) or ".", exist_ok=True)
            with open(args.stats_out, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
        except Exception:
            print("WARN: failed to write stats_out")

    # Always show top of output dir for debugging if running in CI
    try:
        out_dir = os.path.dirname(args.out) or "."
        head = _safe_head(sorted(os.listdir(out_dir)), 5)
        print(f"DEBUG: files in {out_dir}: {head}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
