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
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
from cryptography.hazmat.primitives import hashes


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

def _load_msal_client_credential_from_pfx_b64(pfx_b64: str, pfx_password: str | None) -> dict[str, str]:
    """
    Convert a base64-encoded PFX + password into the MSAL client_credential dict:
      {
        "private_key": "<PEM string>",
        "thumbprint": "<sha1 hex>",
        "public_certificate": "<PEM string>"
      }
    """
    if not pfx_b64:
        raise ValueError("No PFX_B64 provided")

    try:
        pfx_bytes = base64.b64decode(pfx_b64)
    except Exception as e:
        raise RuntimeError(f"PFX base64 decode failed: {e}") from e

    try:
        key, cert, _chain = pkcs12.load_key_and_certificates(
            pfx_bytes, None if pfx_password is None else pfx_password.encode("utf-8")
        )
        if key is None or cert is None:
            raise RuntimeError("PFX contained no private key or certificate")

        thumb_hex = cert.fingerprint(hashes.SHA1()).hex()  # MSAL wants hex string
        private_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode("ascii")
        public_pem = cert.public_bytes(Encoding.PEM).decode("ascii")
        return {"private_key": private_pem, "thumbprint": thumb_hex, "public_certificate": public_pem}
    except Exception as e:
        raise RuntimeError(f"PFX load failed: {e}") from e




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


def _try_fetch_graph(cfg: dict, clouds: set[str], since: str | None, months: str | None) -> tuple[list[Row], str | None]:
    """
    Attempt Graph fetch using certificate creds. On any error, return ([], <error>).
    """
    try:
        tenant = cfg.get("TENANT") or cfg.get("tenant_id") or cfg.get("tenant")
        client_id = cfg.get("CLIENT") or cfg.get("client_id") or cfg.get("client")
        pfx_b64 = cfg.get("PFX_B64") or cfg.get("pfx_base64") or os.environ.get("M365_PFX_BASE64")
        # In your workflow you write "M365_PFX_PASSWORD":"M365_PFX_PASSWORD" into the config.
        # That string is the *env var name*; resolve it here:
        pwd_env_key = cfg.get("M365_PFX_PASSWORD") or "M365_PFX_PASSWORD"
        pfx_password = os.environ.get(pwd_env_key)

        if not tenant or not client_id or not pfx_b64:
            return [], "Graph client not available on this runner"

        # Build MSAL client_credential from the PFX
        client_cred = _load_msal_client_credential_from_pfx_b64(pfx_b64, pfx_password)

        authority_base = cfg.get("authority") or cfg.get("authority_base") or "https://login.microsoftonline.com"
        authority = f"{authority_base.rstrip('/')}/{tenant}"
        graph_base = (cfg.get("graph_base") or "https://graph.microsoft.com").rstrip("/")

        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            authority=authority,
            client_credential=client_cred,  # <-- proper MSAL format
        )

        token = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in token:
            # Return a short, useful message
            short = token.get("error_description") or token.get("error") or "token acquisition failed"
            return [], f"PFX/token error: {short}"

        headers = {"Authorization": f"Bearer {token['access_token']}"}
        # Example endpoint: Message center (latest messages)
        # Adjust your query here (filters by timewindow/clouds handled in transform layer).
        url = f"{graph_base}/v1.0/admin/serviceAnnouncement/messages?$top=200"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return [], f"Graph HTTP {resp.status_code}: {resp.text}"

        payload = resp.json()
        items = payload.get("value", [])

        # Transform into your Row objects using your existing transformer
        rows = transform_graph_messages(items, clouds=clouds, since=since, months=months)
        return rows, None

    except Exception as e:
        return [], f"graph-fetch failed: {e}"

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
