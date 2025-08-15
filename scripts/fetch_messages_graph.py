#!/usr/bin/env python3
# scripts/fetch_messages_graph.py
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Optional deps
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

try:
    import feedparser  # type: ignore
except Exception:  # pragma: no cover
    feedparser = None  # type: ignore

# Local Graph client
try:
    from scripts.graph_client import GraphClient, GraphConfig  # type: ignore
except Exception:
    from graph_client import GraphClient, GraphConfig  # type: ignore

PUBLIC_ROADMAP_JSON = "https://www.microsoft.com/releasecommunications/api/v1/m365"
PUBLIC_ROADMAP_RSS = "https://www.microsoft.com/releasecommunications/api/v2/m365/rss"

p.add_argument("--no-window", action="store_true", help="Disable months/since lookback filtering")


def _session_with_retries() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _iso(dt_: Optional[dt.datetime]) -> str:
    if not dt_:
        return ""
    if dt_.tzinfo is None:
        dt_ = dt_.replace(tzinfo=dt.timezone.utc)
    return dt_.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_date(maybe_date: Any) -> Optional[dt.datetime]:
    if not maybe_date:
        return None
    try:
        from dateutil import parser as dateparser  # type: ignore
        return dateparser.isoparse(str(maybe_date))
    except Exception:
        try:
            return dt.datetime.strptime(str(maybe_date)[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        except Exception:
            return None


# ------------- Cloud selection -------------
def _norm_cloud(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    if s in {"general", "worldwide", "standard", "ww", "worldwide (standard multi-tenant)"}:
        return "worldwide (standard multi-tenant)"
    if s in {"gcc high", "gcch", "high"}:
        return "gcc high"
    if s in {"dod", "us dod", "department of defense"}:
        return "dod"
    if s in {"gcc"}:
        return "gcc"
    return s


def include_by_cloud(item_cloud: str, clouds_selected: List[str]) -> bool:
    if not clouds_selected:
        return True
    sel = {_norm_cloud(c) for c in clouds_selected}
    if not item_cloud:
        return True  # unknown cloud → include
    return _norm_cloud(item_cloud) in sel


# ------------- Roadmap ID extraction -------------
_PATTERNS = [
    # Canonical URL query patterns
    re.compile(r"featureid(?:=|%3[dD])(\d{4,7})", re.I),
    re.compile(r"searchterms?(?:=|%3[dD])(\d{4,7})", re.I),
    # Path pattern
    re.compile(r"/roadmap/feature/(\d{4,7})", re.I),
    # Prose like "Feature ID: 498158" or "Roadmap ID-498158"
    re.compile(r"(?:feature\s*id|roadmap\s*id)\s*[:#-]?\s*(\d{4,7})", re.I),
    # Any 6-digit near the word 'roadmap' or 'feature'
    re.compile(r"(?:roadmap|feature)[^0-9]{0,20}(\d{6})", re.I),
    # Fallback: 49xxxx tokens surrounded by non-alnum
    re.compile(r"(?:^|[^A-Za-z0-9])(49\d{3,4})(?:[^A-Za-z0-9]|$)"),
]


def _ids_from_text(text: str) -> set[str]:
    ids: set[str] = set()
    low = text.lower()
    for pat in _PATTERNS:
        for m in pat.findall(low):
            ids.add(str(m))
    return {i for i in ids if i.isdigit() and 400000 <= int(i) <= 999999}


def extract_roadmap_ids_from_html(html_body: str) -> set[str]:
    if not html_body:
        return set()
    ids = set()
    ids |= _ids_from_text(html_body)
    if BeautifulSoup is None:
        return ids
    import html as htmllib, urllib.parse as up
    soup = BeautifulSoup(htmllib.unescape(html_body), "lxml")
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if not href:
            continue
        parsed = up.urlparse(href)
        q = up.parse_qs(parsed.query)
        if "url" in q:  # redir.aspx?url=<encoded target>
            href = up.unquote(q["url"][0])
        ids |= _ids_from_text(href.lower())
        q2 = up.parse_qs(up.urlparse(href).query)
        for key in ("featureid", "searchterm", "searchterms"):
            for v in q2.get(key, []):
                if v.isdigit() and 400000 <= int(v) <= 999999:
                    ids.add(v)
    return ids


# ------------- Data model -------------
@dataclass
class Row:
    PublicId: str
    Title: str
    Source: str  # graph | public-json | rss | forced
    Product_Workload: str = ""
    Status: str = ""
    LastModified: str = ""
    ReleaseDate: str = ""
    Cloud_instance: str = ""
    Official_Roadmap_link: str = ""
    MessageId: str = ""  # Graph MC id


def _row_link(fid: str) -> str:
    return f"https://www.microsoft.com/microsoft-365/roadmap?searchterms={fid}"


# ------------- Fetchers -------------
def fetch_public_json(stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    s = _session_with_retries()
    try:
        r = s.get(PUBLIC_ROADMAP_JSON, timeout=(5, 30))
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("value") or data.get("items") or []
        stats.setdefault("source_counts", {}).setdefault("public-json-raw", 0)
        stats["source_counts"]["public-json-raw"] = len(items)
        return items
    except Exception as e:  # pragma: no cover
        stats.setdefault("errors", []).append(f"public-json: {e}")
        return []


def transform_public_items(items: List[Dict[str, Any]]) -> List[Row]:
    rows: List[Row] = []
    for it in items:
        lower = {k.lower(): k for k in it.keys()}
        fid = ""
        for key in ("featureid", "publicid", "id", "feature_id"):
            k = lower.get(key)
            if k:
                v = str(it.get(k) or "").strip()
                if v.isdigit():
                    fid = v
                    break
        if not fid:
            for lk in ("link", "roadmaplink", "url", "weburl"):
                k = lower.get(lk)
                if k:
                    m = re.search(r"(\d{6})", str(it.get(k) or ""))
                    if m:
                        fid = m.group(1)
                        break
        if not fid:
            continue
        title = str(it.get(lower.get("title") or "title", "") or "")
        product = str(it.get(lower.get("workload") or lower.get("product") or "workload", "") or "")
        status = str(it.get(lower.get("status") or lower.get("state") or "status", "") or "")
        cloud = str(it.get(lower.get("cloud instance") or lower.get("cloud") or "cloud", "") or "")
        lm = str(it.get(lower.get("lastmodified") or lower.get("lastupdated") or "lastModified", "") or "")
        rel = str(it.get(lower.get("releasedate") or lower.get("startdate") or "releaseDate", "") or "")
        rows.append(
            Row(
                PublicId=fid,
                Title=title,
                Source="public-json",
                Product_Workload=product,
                Status=status,
                LastModified=_iso(_parse_date(lm)),
                ReleaseDate=_iso(_parse_date(rel)),
                Cloud_instance=cloud,
                Official_Roadmap_link=_row_link(fid),
            )
        )
    return rows


def fetch_rss(stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    if feedparser is None:
        stats.setdefault("errors", []).append("rss: feedparser not installed; skipping")
        return []
    try:
        fp = feedparser.parse(PUBLIC_ROADMAP_RSS)
        entries = getattr(fp, "entries", []) or []
        stats.setdefault("source_counts", {}).setdefault("rss-raw", 0)
        stats["source_counts"]["rss-raw"] = len(entries)
        return [e for e in entries]
    except Exception as e:  # pragma: no cover
        stats.setdefault("errors", []).append(f"rss: {e}")
        return []


def transform_rss(entries: List[Dict[str, Any]]) -> List[Row]:
    rows: List[Row] = []
    for e in entries:
        title = str(e.get("title", "") or "")
        summary = str(e.get("summary", "") or "")
        link = str(e.get("link", "") or "")
        fid = ""
        m = re.search(r"(\d{6})", link) or re.search(r"(\d{6})", summary)
        if m:
            fid = m.group(1)
        if not fid:
            continue
        lm = e.get("updated") or e.get("published") or ""
        rows.append(
            Row(
                PublicId=fid,
                Title=title,
                Source="rss",
                LastModified=_iso(_parse_date(lm)),
                Official_Roadmap_link=_row_link(fid),
            )
        )
    return rows


def fetch_graph(cfg_path: Optional[str], since: Optional[dt.datetime], stats: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        cfg = GraphConfig.from_file(cfg_path) if (cfg_path and os.path.exists(cfg_path)) else GraphConfig.from_env()
        client = GraphClient(cfg)
    except Exception as e:
        stats.setdefault("errors", []).append(f"graph-init: {e}")
        return []
    msgs: List[Dict[str, Any]] = []
    try:
        kwargs: Dict[str, Any] = {"top": 100, "include_drafts": True}
        if since:
            kwargs["last_modified_ge"] = since
        for msg in client.iter_service_messages(**kwargs):
            msgs.append(msg)
        stats.setdefault("source_counts", {})["graph-raw"] = len(msgs)
        return msgs
    except Exception as e:  # pragma: no cover
        stats.setdefault("errors", []).append(f"graph-fetch: {e}")
        return []


def transform_graph_messages(msgs: List[Dict[str, Any]]) -> List[Row]:
    rows: List[Row] = []
    for m in msgs:
        mcid = str(m.get("id", "") or "")
        title = str(m.get("title", "") or "")
        services = ", ".join(m.get("services", []) or [])
        classification = str(m.get("classification", "") or m.get("state", "") or "")
        lm = str(m.get("lastModifiedDateTime", "") or "")
        body_html = ""
        try:
            body_html = m.get("body", {}).get("content", "") or ""
        except Exception:
            pass  # body may be missing
        fids = extract_roadmap_ids_from_html(body_html)
        if not fids:
            rows.append(
                Row(
                    PublicId="",
                    Title=title,
                    Source="graph",
                    Product_Workload=services,
                    Status=classification,
                    LastModified=_iso(_parse_date(lm)),
                    MessageId=mcid,
                )
            )
            continue
        for fid in sorted(fids):
            rows.append(
                Row(
                    PublicId=fid,
                    Title=title,
                    Source="graph",
                    Product_Workload=services,
                    Status=classification,
                    LastModified=_iso(_parse_date(lm)),
                    Official_Roadmap_link=_row_link(fid),
                    MessageId=mcid,
                )
            )
    return rows


# ------------- Filtering & merge -------------
def _within_window(row: Row, since: Optional[dt.datetime]) -> bool:
    if since is None:
        return True
    d = _parse_date(row.LastModified) or _parse_date(row.ReleaseDate)
    if not d:
        return True
    return d >= since


def merge_sources(
    graph_rows: List[Row],
    public_rows: List[Row],
    rss_rows: List[Row],
    forced_ids: List[str],
    clouds: List[str],
    since: Optional[dt.datetime],
    stats: Dict[str, Any],
) -> List[Row]:
    out: List[Row] = []
    for r in graph_rows:
        if _within_window(r, since):
            out.append(r)
    for r in public_rows:
        if include_by_cloud(r.Cloud_instance, clouds) and _within_window(r, since):
            out.append(r)
    for r in rss_rows:
        if _within_window(r, since):
            out.append(r)

    have = {r.PublicId for r in out if r.PublicId}
    for fid in forced_ids:
        if fid and fid.isdigit() and fid not in have:
            out.append(Row(PublicId=fid, Title="", Source="forced", Official_Roadmap_link=_row_link(fid)))

    seen: set[Tuple[str, str, str]] = set()
    dedup: List[Row] = []
    for r in out:
        key = (r.Source, r.PublicId or "", r.MessageId or "")
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)

    cnts = {"graph": 0, "public-json": 0, "rss": 0, "forced": 0}
    for r in dedup:
        cnts[r.Source] = cnts.get(r.Source, 0) + 1
    stats.setdefault("source_counts", {}).update(cnts)
    return dedup


# ------------- I/O -------------
def write_csv(rows: List[Row], path: str) -> None:
    cols = [
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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def write_json(rows: List[Row], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)


# ------------- Main -------------
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch M365 Roadmap items from Graph + Public sources")
    p.add_argument("--config", help="Path to graph_config.json (or use TENANT/CLIENT/PFX_B64 env)")
    p.add_argument("--since", help="ISO date (YYYY-MM-DD) start of window")
    p.add_argument("--months", type=int, help="Lookback months (ignored if --since provided)")
    p.add_argument("--ids", default="", help="Comma-separated Roadmap IDs to force-include")
    p.add_argument("--tenant-cloud", default="", help="Deprecated single cloud filter")
    p.add_argument("--cloud", action="append", default=[], help="Repeatable cloud filters (General, GCC, GCC High, DoD)")
    p.add_argument("--no-graph", action="store_true", help="Disable Graph")
    p.add_argument("--no-public-scrape", action="store_true", help="Disable public JSON & RSS")
    p.add_argument("--emit", choices=["csv", "json"], required=True)
    p.add_argument("--out", required=True, help="Output file path")
    p.add_argument("--stats-out", help="Write stats JSON to this path")
    args = p.parse_args(argv)

    clouds: List[str] = []
    if args.tenant_cloud:
        clouds.append(args.tenant_cloud)
    for c in args.cloud:
        clouds.append("Worldwide (Standard Multi-Tenant)" if c.strip().lower() == "general" else c)

    since: Optional[dt.datetime] = None
    if args.since:
        since = _parse_date(args.since)
    elif args.months:
        days = int(max(1, args.months) * 30.5)
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

    forced_ids = [s.strip() for s in (args.ids or "").split(",") if s.strip()]

    stats: Dict[str, Any] = {"args": vars(args), "source_counts": {}, "errors": []}

    graph_msgs: List[Dict[str, Any]] = []
    if not args.no_graph:
        graph_msgs = fetch_graph(args.config, since, stats)
    graph_rows = transform_graph_messages(graph_msgs) if graph_msgs else []

    public_rows: List[Row] = []
    rss_rows: List[Row] = []
    if not args.no_public_scrape:
        try:
            pj = fetch_public_json(stats)
            public_rows = transform_public_items(pj)
        except Exception as e:
            stats.setdefault("errors", []).append(f"public-json-transform: {e}")
        try:
            rss = fetch_rss(stats)
            rss_rows = transform_rss(rss)
        except Exception as e:
            stats.setdefault("errors", []).append(f"rss-transform: {e}")

    merged = merge_sources(graph_rows, public_rows, rss_rows, forced_ids, clouds, since, stats)

    if args.emit == "csv":
        write_csv(merged, args.out)
    else:
        write_json(merged, args.out)

    if args.stats_out:
        os.makedirs(os.path.dirname(args.stats_out) or ".", exist_ok=True)
        with open(args.stats_out, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    print(
        f"Done. rows={len(merged)} sources={stats.get('source_counts')} "
        f"errors={len(stats.get('errors', []))}"
    )
    if stats.get("errors"):
        for e in stats["errors"]:
            print("WARN:", e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
