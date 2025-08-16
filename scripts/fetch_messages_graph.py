#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fetch Microsoft 365 Roadmap-related items, preferring Microsoft Graph messages
and falling back to public sources and/or seed IDs.

Outputs a normalized table of rows and optional fetch statistics.

Usage (examples)
---------------
python scripts/fetch_messages_graph.py \
  --config graph_config.json \
  --cloud "Worldwide (Standard Multi-Tenant)" --cloud GCC \
  --emit csv --out output/roadmap_report_master.csv --stats-out output/roadmap_report_fetch_stats.json

python scripts/fetch_messages_graph.py \
  --config graph_config.json \
  --emit json --out output/roadmap_report_master.json --seed-ids "496654,486856"
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

# Optional deps — we guard imports so this script still runs without them.
try:
    import msal  # type: ignore
except Exception:  # pragma: no cover - optional import
    msal = None  # type: ignore[assignment]

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional import
    requests = None  # type: ignore[assignment]

try:
    from cryptography import x509  # type: ignore
    from cryptography.hazmat.primitives import hashes  # type: ignore
    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption  # type: ignore
except Exception:  # pragma: no cover - optional import
    x509 = None  # type: ignore[assignment]
    pkcs12 = None  # type: ignore[assignment]
    Encoding = PrivateFormat = NoEncryption = hashes = None  # type: ignore[assignment]

# --------------------------- Data model ---------------------------


@dataclass
class Row:
    PublicId: str
    Title: str
    Source: str  # 'graph' | 'public-json' | 'rss' | 'seed'
    Product_Workload: str = ""
    Status: str = ""
    LastModified: str = ""
    ReleaseDate: str = ""
    Cloud_instance: str = ""
    Official_Roadmap_link: str = ""
    MessageId: str = ""  # Graph message id, if any


# canonical export field order
_OUTPUT_FIELDS: list[str] = [
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

# --------------------------- Utilities ---------------------------


def _split_csv_like(value: str) -> list[str]:
    """Split a comma/pipe/semicolon/whitespace separated string into clean tokens."""
    if not value:
        return []
    parts = re.split(r"[,\|;\s]+", value.strip())
    out: list[str] = []
    for p in parts:
        p = p.strip().strip('"').strip("'")
        if p:
            out.append(p)
    return out


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert a `Row` or mapping-like object to a plain dict with stable fields."""
    if is_dataclass(row):
        data = asdict(row)
    elif isinstance(row, dict):
        data = dict(row)
    else:
        data = {k: getattr(row, k, "") for k in _OUTPUT_FIELDS}
    # Ensure all fields are present
    return {k: ("" if data.get(k) is None else data.get(k, "")) for k in _OUTPUT_FIELDS}


def write_csv(rows: Iterable[Any], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_OUTPUT_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(_row_to_dict(r))


def write_json(rows: Iterable[Any], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out_list = [_row_to_dict(r) for r in rows]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_list, f, indent=2, ensure_ascii=False)


# --------------------------- Clouds ---------------------------

_CLOUD_CANON = {
    "worldwide (standard multi-tenant)": "Worldwide (Standard Multi-Tenant)",
    "general": "Worldwide (Standard Multi-Tenant)",
    "worldwide": "Worldwide (Standard Multi-Tenant)",
    "gcc": "GCC",
    "gcc high": "GCC High",
    "gcch": "GCC High",
    "dod": "DoD",
}

# If a row has one of these labels, treat it as matching the Worldwide label too.
_WORLDWIDE_ALIASES = {"Worldwide", "Worldwide (Standard Multi-Tenant)", "General", ""}


def normalize_clouds(label: str | Sequence[str] | None) -> set[str]:
    """Return a set of canonical cloud labels from free-form input."""
    if label is None:
        return set()
    if isinstance(label, str):
        labels = _split_csv_like(label)
    else:
        labels = list(label)
    out: set[str] = set()
    for item in labels:
        key = item.strip().lower()
        canon = _CLOUD_CANON.get(key, None)
        if canon:
            out.add(canon)
        else:
            # keep raw (title-cased) if not recognized, but don't spam
            if item.strip():
                out.add(item.strip())
    return out


def include_by_cloud(row_cloud: str, selected: set[str]) -> bool:
    """Decide if a row should be included given selected cloud set (empty = include all)."""
    if not selected:
        return True
    rc = row_cloud.strip()
    if rc in _WORLDWIDE_ALIASES and "Worldwide (Standard Multi-Tenant)" in selected:
        return True
    return rc in selected


# --------------------------- Config & Args ---------------------------


def _load_cfg(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _graph_env_password_name(cfg: dict[str, Any]) -> str:
    # Allow the config to specify which env var contains the PFX password.
    # Default is "M365_PFX_PASSWORD".
    name = cfg.get("M365_PFX_PASSWORD") or cfg.get("pfx_password_env") or "M365_PFX_PASSWORD"
    return str(name)


def _has_valid_graph_config(cfg: dict[str, Any]) -> bool:
    tenant = (cfg.get("TENANT") or cfg.get("tenant") or "").strip()
    client = (cfg.get("CLIENT") or cfg.get("client") or "").strip()
    pfx_b64 = (cfg.get("PFX_B64") or cfg.get("pfx_b64") or "").strip()
    pw_env = _graph_env_password_name(cfg)
    pw = os.environ.get(pw_env, "")
    return all([tenant, client, pfx_b64, pw])


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="fetch_messages_graph.py")
    p.add_argument("--config", default="graph_config.json", help="Path to graph/public config JSON.")
    p.add_argument("--since", default="", help="Only include items on/after YYYY-MM-DD")
    p.add_argument("--months", type=int, default=0, help="Only include items in last N months")
    p.add_argument(
        "--cloud",
        action="append",
        default=[],
        help="Cloud label to include (repeat). e.g. 'Worldwide (Standard Multi-Tenant)', 'GCC', 'GCC High', 'DoD'",
    )
    p.add_argument("--no-graph", action="store_true", help="Skip Microsoft Graph (fallbacks only).")
    p.add_argument(
        "--seed-ids",
        default="",
        help="Comma/pipe separated numeric PublicId list to seed rows (forced include).",
    )
    p.add_argument("--emit", required=True, choices=["csv", "json"], help="Output format.")
    p.add_argument("--out", required=True, help="Output file path.")
    p.add_argument("--stats-out", default="", help="Optional stats JSON output.")
    return p.parse_args(argv)


# --------------------------- Graph fetcher ---------------------------

_RE_ROADMAP_ID = re.compile(r"(?:Roadmap\s*ID|Feature\s*ID|RoadmapID|Roadmap)\s*[:#]?\s*([0-9]{5,7})", re.I)


def _graph_token_from_pfx(cfg: dict[str, Any]) -> tuple[str, str] | tuple[None, str]:
    """Acquire a Graph token using app cert (PFX in base64). Returns (token, warn)."""
    if msal is None or pkcs12 is None or Encoding is None or hashes is None:  # missing deps
        return (None, "Graph client not available on this runner (missing msal/cryptography).")

    tenant = (cfg.get("TENANT") or cfg.get("tenant") or "").strip()
    client = (cfg.get("CLIENT") or cfg.get("client") or "").strip()
    pfx_b64 = (cfg.get("PFX_B64") or cfg.get("pfx_b64") or "").strip()
    pw_env = _graph_env_password_name(cfg)
    pw_text = os.environ.get(pw_env, "")

    try:
        pfx_bytes = base64.b64decode(pfx_b64.encode("utf-8"), validate=False)
        key, cert, _chain = pkcs12.load_key_and_certificates(
            pfx_bytes, pw_text.encode("utf-8") if pw_text else None
        )
        if key is None or cert is None:
            return (None, "PFX decode yielded no key/cert (check password).")
        private_key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode("utf-8")
        public_cert_pem = cert.public_bytes(Encoding.PEM).decode("utf-8")
        thumb = cert.fingerprint(hashes.SHA1()).hex()

        authority = f"https://login.microsoftonline.com/{tenant}"
        app = msal.ConfidentialClientApplication(
            client_id=client,
            authority=authority,
        )
        cred = {"private_key": private_key_pem, "thumbprint": thumb, "public_certificate": public_cert_pem}
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"], client_credential=cred)
        if not result or "access_token" not in result:
            return (None, f"Token acquisition failed: {result!r}")
        return (result["access_token"], "")
    except Exception as e:  # pragma: no cover - runtime env issues
        return (None, f"PFX/token error: {e}")


def _fetch_graph_messages(cfg: dict[str, Any], selected_clouds: set[str]) -> list[Row]:
    """Fetch service announcement messages, extract Roadmap IDs, and map to Rows."""
    token, warn = _graph_token_from_pfx(cfg)
    if token is None:
        if warn:
            print(f"WARN: graph-fetch failed: {warn}")
        return []

    if requests is None:
        print("WARN: graph-fetch failed: 'requests' not available")
        return []

    url = "https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/messages?$top=100"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 403:
            print(f"WARN: Graph call forbidden (403): {resp.text[:200]}")
            return []
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:  # pragma: no cover - runtime
        print(f"WARN: Graph call failed: {e}")
        return []

    values = payload.get("value", [])
    rows: list[Row] = []
    for msg in values:
        body_html = (msg.get("body", {}) or {}).get("content", "") or ""
        title = (msg.get("title") or "").strip()
        message_id = (msg.get("id") or "").strip()
        services = msg.get("services") or []
        last_mod = msg.get("lastModifiedDateTime") or ""
        # Try to find Roadmap IDs in title/body
        ids: set[str] = set()
        for text in (title, body_html):
            for m in _RE_ROADMAP_ID.finditer(text or ""):
                ids.add(m.group(1))
        # If no explicit Roadmap id, skip (we only export roadmap-ish items)
        if not ids:
            continue
        for rid in sorted(ids):
            row = Row(
                PublicId=rid,
                Title=title or f"[{rid}]",
                Source="graph",
                Product_Workload="/".join(s for s in services if isinstance(s, str)),
                LastModified=last_mod,
                Cloud_instance="",  # message doesn't clearly map to tenant cloud; leave empty
                Official_Roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}",
                MessageId=message_id,
            )
            # Cloud filter
            if not include_by_cloud(row.Cloud_instance, selected_clouds):
                continue
            rows.append(row)
    return rows


# --------------------------- Public fallbacks ---------------------------


def _fetch_public_json(cfg: dict[str, Any], selected_clouds: set[str]) -> list[Row]:
    """Optional public JSON feed (if a URL is provided in config)."""
    url = (cfg.get("public_json_url") or "").strip()
    if not url:
        return []
    if requests is None:
        print("WARN: public-json fetch skipped (requests unavailable).")
        return []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"WARN: public-json fetch failed: {e}")
        return []

    rows: list[Row] = []
    # Make a best-effort mapping (expect a list of dicts)
    if isinstance(data, dict) and "value" in data:
        data = data["value"]
    if not isinstance(data, list):
        return []
    for it in data:
        rid = str(it.get("PublicId") or it.get("Id") or it.get("id") or "").strip()
        if not rid.isdigit():
            continue
        cloud = str(it.get("Cloud_instance") or it.get("Cloud") or "").strip()
        row = Row(
            PublicId=rid,
            Title=str(it.get("Title") or f"[{rid}]"),
            Source="public-json",
            Product_Workload=str(it.get("Product_Workload") or it.get("Product") or ""),
            Status=str(it.get("Status") or ""),
            LastModified=str(it.get("LastModified") or ""),
            ReleaseDate=str(it.get("ReleaseDate") or ""),
            Cloud_instance=cloud,
            Official_Roadmap_link=it.get("Official_Roadmap_link")
            or f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}",
            MessageId=str(it.get("MessageId") or ""),
        )
        if include_by_cloud(row.Cloud_instance, selected_clouds):
            rows.append(row)
    return rows


def _fetch_public_rss(cfg: dict[str, Any], selected_clouds: set[str]) -> list[Row]:
    """Optional RSS feed (if URL in config). We only extract IDs/titles."""
    url = (cfg.get("public_rss_url") or "").strip()
    if not url:
        return []
    if requests is None:
        print("WARN: public-rss fetch skipped (requests unavailable).")
        return []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        print(f"WARN: public-rss fetch failed: {e}")
        return []

    # naive parse for roadmap IDs and titles
    rows: list[Row] = []
    # <title>something (Roadmap ID: 123456)</title>
    for m in re.finditer(r"<title>(.*?)</title>", text, re.I | re.S):
        title_html = m.group(1)
        title_clean = re.sub(r"<[^>]+>", "", title_html).strip()
        ids = _RE_ROADMAP_ID.findall(title_clean)
        for rid in ids:
            row = Row(
                PublicId=rid,
                Title=title_clean or f"[{rid}]",
                Source="rss",
                Official_Roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}",
            )
            if include_by_cloud(row.Cloud_instance, selected_clouds):
                rows.append(row)
    return rows


# --------------------------- Merge, filter, seed ---------------------------


def _apply_time_window(rows: list[Row], since: str, months: int) -> list[Row]:
    if not since and not months:
        return rows
    cutoff: Optional[dt.date] = None
    if since:
        try:
            cutoff = dt.date.fromisoformat(since)
        except Exception:
            cutoff = None
    elif months:
        cutoff = dt.date.today() - dt.timedelta(days=months * 30)

    def parse_date(s: str) -> Optional[dt.date]:
        if not s:
            return None
        # accept YYYY-MM-DD or ISO datetime
        try:
            if len(s) >= 10:
                return dt.date.fromisoformat(s[:10])
        except Exception:
            return None
        return None

    out: list[Row] = []
    for r in rows:
        if cutoff is None:
            out.append(r)
            continue
        # Prefer LastModified, else ReleaseDate
        d = parse_date(r.LastModified) or parse_date(r.ReleaseDate)
        if d is None or d >= cutoff:
            out.append(r)
    return out


def _merge_rows(rows: list[Row]) -> list[Row]:
    """De-dupe by PublicId, keeping best Source priority: graph > public-json > rss > seed."""
    pri = {"graph": 4, "public-json": 3, "rss": 2, "seed": 1}
    best: dict[str, Row] = {}
    for r in rows:
        pid = r.PublicId.strip()
        if not pid:
            continue
        if pid not in best or pri.get(r.Source, 0) > pri.get(best[pid].Source, 0):
            best[pid] = r
    return [best[k] for k in sorted(best.keys(), key=lambda x: int(x))]


def _seed_rows(seed_ids: str, selected_clouds: set[str]) -> list[Row]:
    out: list[Row] = []
    for s in _split_csv_like(seed_ids):
        if not s.isdigit():
            continue
        rid = s
        r = Row(
            PublicId=rid,
            Title=f"[{rid}]",
            Source="seed",
            Cloud_instance="",
            Official_Roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}",
        )
        if include_by_cloud(r.Cloud_instance, selected_clouds):
            out.append(r)
    return out


def _write_discovered_ids(all_rows: list[Row], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    ids_all = sorted({r.PublicId for r in all_rows if r.PublicId})
    with open(os.path.join(out_dir, "discovered_ids.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PublicId"])
        for pid in ids_all:
            w.writerow([pid])

    # Common subsets (for quick human inspection)
    with open(os.path.join(out_dir, "discovered_ids_gcc.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PublicId"])
        for r in all_rows:
            if r.Cloud_instance == "GCC":
                w.writerow([r.PublicId])

    with open(os.path.join(out_dir, "discovered_ids_loose.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PublicId"])
        for r in all_rows:
            if r.Source != "seed":
                w.writerow([r.PublicId])


# --------------------------- Main ---------------------------


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    cfg = _load_cfg(args.config)

    # Build selected cloud set
    selected_clouds = normalize_clouds(args.cloud)

    # Initialize stats early so later references never crash
    stats: dict[str, Any] = {
        "sources": {"graph": 0, "public-json": 0, "rss": 0, "seed": 0},
        "errors": [],
    }

    # Auto-fallback if graph secrets are missing/invalid
    if not args.no_graph and not _has_valid_graph_config(cfg):
        print("INFO: Graph credentials missing/invalid → using public fallback only (as if --no-graph).")
        args.no_graph = True

    # Collect rows (graph → public → rss → seed)
    collected: list[Row] = []
    try:
        if not args.no_graph:
            graph_rows = _fetch_graph_messages(cfg, selected_clouds)
            stats["sources"]["graph"] = len([r for r in graph_rows if r.Source == "graph"])
            collected.extend(graph_rows)
    except Exception as e:  # pragma: no cover
        stats["errors"].append(f"graph: {e}")

    try:
        pub_rows = _fetch_public_json(cfg, selected_clouds)
        stats["sources"]["public-json"] = len([r for r in pub_rows if r.Source == "public-json"])
        collected.extend(pub_rows)
    except Exception as e:  # pragma: no cover
        stats["errors"].append(f"public-json: {e}")

    try:
        rss_rows = _fetch_public_rss(cfg, selected_clouds)
        stats["sources"]["rss"] = len([r for r in rss_rows if r.Source == "rss"])
        collected.extend(rss_rows)
    except Exception as e:  # pragma: no cover
        stats["errors"].append(f"rss: {e}")

    # Seeds (forced IDs)
    try:
        seed_rows = _seed_rows(args.seed_ids, selected_clouds)
        stats["sources"]["seed"] = len(seed_rows)
        collected.extend(seed_rows)
    except Exception as e:  # pragma: no cover
        stats["errors"].append(f"seed: {e}")

    # Time filter, then de-dup/merge by PublicId
    collected = _apply_time_window(collected, args.since, args.months)
    merged = _merge_rows(collected)

    # Emit
    if args.emit == "csv":
        write_csv(merged, args.out)
    else:
        write_json(merged, args.out)

    # Stats file
    if args.stats_out:
        out_stats = {
            "rows": len(merged),
            "sources": stats["sources"],
            "errors": stats["errors"],
            "cloud_filter": sorted(list(selected_clouds)),
            "since": args.since,
            "months": args.months,
        }
        os.makedirs(os.path.dirname(args.stats_out) or ".", exist_ok=True)
        with open(args.stats_out, "w", encoding="utf-8") as f:
            json.dump(out_stats, f, indent=2, ensure_ascii=False)

    # Convenience debug artifacts
    out_dir = os.path.dirname(args.out) or "."
    try:
        _write_discovered_ids(merged, out_dir)
    except Exception:
        pass

    # Log summary & dir contents (handy in CI logs)
    print(
        f"Done. rows={len(merged)} sources={stats['sources']} errors={len(stats['errors'])}"
    )
    try:
        files = sorted(os.listdir(out_dir))
        print(f"DEBUG: files in {out_dir}: {files}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
