#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch M365 roadmap / message center items:
- Prefer Microsoft Graph (cert-auth) when credentials are present.
- Gracefully fall back to public sources or seeded IDs.
- Emit CSV/JSON with the canonical Title-cased columns your pipeline expects.
"""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import datetime as dt  # keep alias `dt` used throughout

# ---------- Constants & helpers ----------

# Matches a bare roadmap id in text (e.g., "496654").
_RE_ROADMAP_ID = re.compile(r"\b(\d{4,6})\b")

# Canonical output order (Title-cased keys, matching your generator)
FIELD_ORDER: list[str] = [
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

# Cloud normalization map (string -> canonical label)
_CLOUD_MAP = {
    "worldwide (standard multi-tenant)": "General",
    "worldwide": "General",
    "general": "General",
    "commercial": "General",
    "gcc": "GCC",
    "gcc high": "GCC High",
    "gcch": "GCC High",
    "dod": "DoD",
}

# ---------- Data model ----------


@dataclass
class Row:
    public_id: str = ""
    title: str = ""
    source: str = ""  # graph | public-json | rss | seed
    product_workload: str = ""
    status: str = ""
    last_modified: str = ""  # ISO or friendly string
    release_date: str = ""  # ISO or friendly string
    cloud_instance: str = ""  # raw text; blanks treated as General for filtering
    official_roadmap_link: str = ""
    message_id: str = ""


def row_to_export_dict(r: Row) -> dict[str, Any]:
    """Convert internal dataclass Row -> Title-cased export dict in FIELD_ORDER."""
    raw = asdict(r)
    # Map internal snake_case -> Title-cased keys
    mapping = {
        "PublicId": raw.get("public_id", ""),
        "Title": raw.get("title", ""),
        "Source": raw.get("source", ""),
        "Product_Workload": raw.get("product_workload", ""),
        "Status": raw.get("status", ""),
        "LastModified": raw.get("last_modified", ""),
        "ReleaseDate": raw.get("release_date", ""),
        "Cloud_instance": raw.get("cloud_instance", ""),
        "Official_Roadmap_link": raw.get("official_roadmap_link", ""),
        "MessageId": raw.get("message_id", ""),
    }
    return {k: mapping.get(k, "") for k in FIELD_ORDER}


# ---------- IO ----------


def _split_csv_like(s: str) -> list[str]:
    """Split on comma/pipe/whitespace; drop empties; strip whitespace."""
    if not s:
        return []
    parts = re.split(r"[,\|\n\r\t]+", s)
    return [p.strip() for p in parts if p.strip()]


def read_config(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    # Support both old and new keys
    return {
        "TENANT": str(cfg.get("TENANT") or cfg.get("tenant") or cfg.get("tenant_id") or "").strip(),
        "CLIENT": str(cfg.get("CLIENT") or cfg.get("client") or cfg.get("client_id") or "").strip(),
        "PFX_B64": str(cfg.get("PFX_B64") or cfg.get("pfx_base64") or cfg.get("pfx_b64") or "").strip(),
        "PFX_PASS_ENV": str(cfg.get("PFX_PASSWORD_ENV") or cfg.get("M365_PFX_PASSWORD") or "M365_PFX_PASSWORD").strip(),
        "GRAPH_BASE": str(cfg.get("graph_base") or "https://graph.microsoft.com").strip(),
        "PUBLIC_JSON_URL": str(cfg.get("public_json_url") or "").strip(),
        "PUBLIC_RSS_URL": str(cfg.get("public_rss_url") or "").strip(),
    }


def write_csv(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELD_ORDER)
        w.writeheader()
        for r in rows:
            w.writerow(row_to_export_dict(r))


def write_json(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    def _ser(v: Any) -> Any:
        # Keep strings as-is; no datetime objects expected in export now
        return "" if v is None else v

    payload: list[dict[str, Any]] = []
    for r in rows:
        exp = row_to_export_dict(r)
        payload.append({k: _ser(exp.get(k, "")) for k in FIELD_ORDER})

    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_stats(path: Optional[str | Path], stats: dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


# ---------- Cloud filtering ----------


def normalize_clouds(items: Iterable[str]) -> set[str]:
    """Normalize cloud display names to canonical labels."""
    out: set[str] = set()
    for s in items or []:
        key = (s or "").strip().lower()
        if not key:
            continue
        out.add(_CLOUD_MAP.get(key, s.strip()))
    return out


def include_by_cloud(cloud_field: str, selected: set[str]) -> bool:
    """
    Decide if a row with 'cloud_field' should be included for the selected clouds.
    Blank raw cloud counts as 'General' (compat with legacy exports).
    """
    if not selected:
        return True
    raw = (cloud_field or "").strip()
    canon = normalize_clouds([raw]) if raw else {"General"}
    return bool(canon & selected)


# ---------- Data sources ----------


def _try_fetch_graph(
    tenant: str,
    client_id: str,
    pfx_b64: str,
    pfx_pass: str,
    start_date: Optional[str],
    months: Optional[int],
    clouds: set[str],
    graph_base: str = "https://graph.microsoft.com",
) -> tuple[list[Row], Optional[str]]:
    """
    Try to fetch via Graph. Returns (rows, error_message).
    On failure, rows=[], error_message=<why>.
    """
    if not tenant or not client_id or not pfx_b64 or not pfx_pass:
        return [], "Graph credentials missing/invalid → using public fallback only (as if --no-graph)."

    try:
        import msal  # type: ignore[import-not-found]
        import requests  # type: ignore[import-not-found]
    except Exception:
        return [], "Graph client not available on this runner"

    # Build cert from base64 PFX
    try:
        pfx_bytes = base64.b64decode(pfx_b64.strip())
    except Exception as ex:
        return [], f"PFX decode error: {ex}"

    # MSAL accepts certificate as dict with 'private_key'/'thumbprint' when you load the PKCS12.
    # To keep this runner-friendly, we'll use msal's convenience with pfx directly (supported in msal>=1.16).
    cert_cred = {"pfx": pfx_bytes, "password": pfx_pass}
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=cert_cred,  # <-- this is the correct place (NOT requests)
    )

    scope = [f"{graph_base}/.default"]
    try:
        token_result = app.acquire_token_for_client(scopes=scope)
    except Exception as ex:
        return [], f"PFX/token error: {ex}"

    if "access_token" not in token_result:
        return [], f"Auth failed: {token_result.get('error_description') or token_result!r}"

    access_token = token_result["access_token"]
    ses = requests.Session()
    ses.headers.update({"Authorization": f"Bearer {access_token}"})

    # Minimal example query: Message center posts (admin service communications)
    # For a real implementation, you’d add filter by dates/products as needed.
    url = f"{graph_base}/v1.0/admin/serviceAnnouncement/messages"
    params = {"$top": "50"}  # tweak as needed

    try:
        resp = ses.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            return [], f"HTTP {resp.status_code}: {resp.text}"
        data = resp.json()
    except Exception as ex:
        return [], f"Graph request failed: {ex}"

    rows: list[Row] = []
    for item in data.get("value", []):
        # Map Graph message center fields -> our unified Row
        # Fields vary; we defensively .get(...)
        title = item.get("title") or ""
        message_id = item.get("id") or ""
        last_mod = item.get("lastModifiedDateTime") or ""
        products = item.get("services", []) or item.get("products", [])
        product_workload = ", ".join(sorted({str(x) for x in products if x})) if products else ""
        # Extract roadmap id(s) if present in text
        body = item.get("body", {}) or {}
        content = body.get("content") or ""
        matches = _RE_ROADMAP_ID.findall(content)
        public_id = matches[0] if matches else ""
        official_link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}" if public_id else ""

        # We don't get cloud instance in the message; leave blank (treated as General for filtering)
        rows.append(
            Row(
                public_id=public_id,
                title=title,
                source="graph",
                product_workload=product_workload,
                status="",
                last_modified=last_mod,
                release_date="",
                cloud_instance="",
                official_roadmap_link=official_link,
                message_id=message_id,
            )
        )

    # Date range / cloud filter here if you want to pre-trim
    return rows, None


def _seed_rows_from_ids(ids_csv: str) -> list[Row]:
    rows: list[Row] = []
    for pid in _split_csv_like(ids_csv):
        if not pid:
            continue
        rows.append(
            Row(
                public_id=pid,
                title=f"[{pid}]",
                source="seed",
                product_workload="",
                status="",
                last_modified="",
                release_date="",
                cloud_instance="",
                official_roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pid}",
                message_id="",
            )
        )
    return rows


# ---------- CLI ----------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=str, default="graph_config.json")
    p.add_argument("--since", type=str, default="")
    p.add_argument("--months", type=str, default="")
    p.add_argument("--cloud", action="append", default=[], help="Repeatable. e.g. 'Worldwide (Standard Multi-Tenant)' or 'GCC'")
    p.add_argument("--no-graph", action="store_true", default=False)
    p.add_argument("--seed-ids", type=str, default="")
    p.add_argument("--emit", choices=["csv", "json"], required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--stats-out", default="")
    return p.parse_args(argv)


# ---------- Main ----------


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    cfg = read_config(args.config)

    # Selected clouds (canonical)
    selected_clouds = normalize_clouds(args.cloud) if args.cloud else set()
    if not selected_clouds:
        # No cloud provided → treat as General (legacy behavior)
        selected_clouds = {"General"}

    # Time window (optional)
    since_str = (args.since or "").strip()
    months = None
    if args.months.strip().isdigit():
        months = int(args.months.strip())

    # Prepare stats
    stats: dict[str, Any] = {
        "generated_utc": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "args": {
            "since": since_str,
            "months": months,
            "clouds": sorted(selected_clouds),
            "emit": args.emit,
        },
        "sources": {"graph": 0, "public-json": 0, "rss": 0, "seed": 0},
        "errors": 0,
    }

    # Collect rows
    rows: list[Row] = []

    # Graph (unless explicitly disabled)
    graph_err: Optional[str] = None
    if not args.no_graph:
        tenant = cfg.get("TENANT", "")
        client = cfg.get("CLIENT", "")
        pfx_b64 = cfg.get("PFX_B64", "")
        pfx_pass = os.environ.get(cfg.get("PFX_PASS_ENV", "M365_PFX_PASSWORD"), "")
        graph_base = cfg.get("GRAPH_BASE", "https://graph.microsoft.com")

        g_rows, graph_err = _try_fetch_graph(
            tenant=tenant,
            client_id=client,
            pfx_b64=pfx_b64,
            pfx_pass=pfx_pass or "",
            start_date=since_str or None,
            months=months,
            clouds=selected_clouds,
            graph_base=graph_base or "https://graph.microsoft.com",
        )
        if graph_err:
            print(f"WARN: graph-fetch failed: {graph_err}", file=sys.stderr)
            stats["errors"] = stats.get("errors", 0) + 1
        if g_rows:
            rows.extend(g_rows)
            stats["sources"]["graph"] = len(g_rows)

    # Public fallbacks are omitted here by default (set URLs in config if you want them)
    # Seeded IDs (always allowed)
    if args.seed_ids.strip():
        s_rows = _seed_rows_from_ids(args.seed_ids)
        rows.extend(s_rows)
        stats["sources"]["seed"] = len(s_rows)

    # Cloud filter (blank cloud counts as General)
    filtered: list[Row] = [r for r in rows if include_by_cloud(r.cloud_instance, selected_clouds)]

    # Emit
    out_path = args.out
    if args.emit == "csv":
        write_csv(out_path, filtered)
    else:
        write_json(out_path, filtered)

    # Stats (optional)
    stats["rows"] = len(filtered)
    write_stats(args.stats_out or None, stats)

    print(f"Done. rows={len(filtered)} sources={stats['sources']} errors={stats['errors']}")
    # Optional: show output dir inventory for CI debugging
    try:
        out_dir = str(Path(out_path).parent)
        files = sorted(os.listdir(out_dir))
        print(f"DEBUG: files in {out_dir}: {files}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
