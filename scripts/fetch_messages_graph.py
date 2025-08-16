#!/usr/bin/env python3
"""
Fetch Microsoft 365 Message Center items from Graph (preferred) with a resilient
fallback path (public/RSS stub), then emit a unified master CSV/JSON.

Key behaviors
-------------
- Defaults to Graph. If credentials are missing or Graph fails, we log a warning
  and continue with the fallback path instead of exiting.
- `--no-graph` forces the fallback path even if secrets are present.
- Treats blank/None Cloud_instance as "General" so cloud filtering won't drop it.
- Supports cloud filtering via one or many --cloud flags:
    --cloud "Worldwide (Standard Multi-Tenant)"  (maps to "General")
    --cloud "GCC" | "GCC High" | "DoD"
- Writes a compact stats JSON and prints a concise summary line.
- Emits CSV or JSON (or both by calling twice).

Example
-------
python scripts/fetch_messages_graph.py \
  --config graph_config.json \
  --cloud "Worldwide (Standard Multi-Tenant)" \
  --emit csv --out output/roadmap_report_master.csv --stats-out output/roadmap_report_fetch_stats.json

Requirements
------------
- msal, cryptography, requests, pandas not required here (no heavy deps used).
- `graph_config.json` like:
    {
      "tenant": "...",
      "client_id": "...",
      "pfx_base64": "...",         # base64 of .pfx
      "pfx_password_env": "M365_PFX_PASSWORD"
    }
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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

# Optional imports used only when Graph is enabled
try:
    import msal  # type: ignore
    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
    from cryptography.hazmat.primitives import hashes  # for thumbprint
    HAVE_GRAPH_DEPS = True
except Exception:
    HAVE_GRAPH_DEPS = False


# ---------- Constants

HEADERS: List[str] = [
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

CLOUD_CANONICAL = {
    "general": "General",
    "worldwide (standard multi-tenant)": "General",
    "worldwide": "General",
    "public": "General",
    "gcc": "GCC",
    "gcc high": "GCC High",
    "gcch": "GCC High",
    "dod": "DoD",
    "usgovdod": "DoD",
}

# For a quick sanity extraction of a number-like ID from titles/links
_RE_ROADMAP_ID = re.compile(r"(?<!\d)(\d{3,})")


# ---------- Data model

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


# ---------- Utilities

def normalize_clouds(raw: Optional[str]) -> Set[str]:
    """Return a set of canonical cloud labels from input string(s)."""
    if not raw:
        return {"General"}  # treat blank as General
    parts = re.split(r"[;,/|]+", raw) if isinstance(raw, str) else [str(raw)]
    out: Set[str] = set()
    for p in parts:
        key = p.strip().lower()
        if not key:
            continue
        out.add(CLOUD_CANONICAL.get(key, p.strip()))
    return out or {"General"}


def include_by_cloud(row_cloud: Optional[str], wanted: Set[str]) -> bool:
    """True if the row cloud set intersects the wanted set. Blank => General."""
    if not wanted:
        return True
    row_set = normalize_clouds(row_cloud or "")
    return not row_set.isdisjoint(wanted)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="Path to graph_config.json")
    p.add_argument("--since", help="Only include items last modified on/after this date (YYYY-MM-DD)")
    p.add_argument("--months", type=int, help="Only include items within the last N months")
    p.add_argument("--cloud", action="append", default=[], help="Cloud filter. Repeatable. E.g. 'Worldwide (Standard Multi-Tenant)', 'GCC', 'GCC High', 'DoD'")
    p.add_argument("--emit", choices=["csv", "json"], required=True, help="Output format")
    p.add_argument("--out", required=True, help="Output path for CSV or JSON")
    p.add_argument("--stats-out", help="Write fetch stats JSON here")
    p.add_argument("--no-graph", action="store_true", help="Skip Graph and use fallback only")
    return p.parse_args(argv)


def load_config(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def secrets_present(cfg: Dict[str, str]) -> bool:
    needed = ["tenant", "client_id", "pfx_base64", "pfx_password_env"]
    return all(cfg.get(x) for x in needed) and bool(os.environ.get(cfg.get("pfx_password_env", "")))


def _since_from_args(since: Optional[str], months: Optional[int]) -> Optional[dt.datetime]:
    if since:
        try:
            return dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    if months:
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months)
    return None


def _thumbprint_sha1(cert_der: bytes) -> str:
    # Hex lower for consistency with user logs
    h = hashes.Hash(hashes.SHA1())
    h.update(cert_der)
    return h.finalize().hex()


def get_graph_token_with_pfx(cfg: Dict[str, str]) -> Tuple[str, str]:
    """
    Returns (access_token, thumbprint). Raises on failure.
    Uses msal confidential client with certificate craft from PKCS#12 (PFX).
    """
    tenant = cfg["tenant"]
    client_id = cfg["client_id"]
    pfx_b64 = cfg["pfx_base64"]
    pwd_env = cfg["pfx_password_env"]
    pwd = os.environ.get(pwd_env, "")

    blob = base64.b64decode(pfx_b64)
    key, cert, _chain = pkcs12.load_key_and_certificates(blob, pwd.encode() if pwd else None)
    if key is None or cert is None:
        raise ValueError("PFX did not yield key+cert")
    # Dump PEM private key for MSAL usage
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    cert_der = cert.public_bytes(Encoding.DER)
    thumb = _thumbprint_sha1(cert_der)

    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential={"private_key": key_pem, "thumbprint": thumb},
    )
    scope = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_for_client(scopes=scope)
    if "access_token" not in result:
        raise RuntimeError(f"MSAL failed: {result.get('error_description') or result}")
    return result["access_token"], thumb


def fetch_graph_messages(cfg: Dict[str, str], since_dt: Optional[dt.datetime]) -> List[Row]:
    """
    Calls Graph Service Communications API:
      GET https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/messages?$top=100
    Paginates until exhausted. Filters by since_dt if provided.
    Maps to our Row structure. Cloud_instance is unknown in Graph payload, so we map blank->General.
    """
    import requests  # local import to keep module import lighter

    token, thumb = get_graph_token_with_pfx(cfg)
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/messages?$top=100"

    rows: List[Row] = []
    fetched = 0
    while url:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        for item in data.get("value", []):
            fetched += 1
            msg_id = item.get("id") or ""
            title = item.get("title") or ""
            last_mod = item.get("lastModifiedDateTime") or ""
            rel = (item.get("startDateTime") or "")  # often the “startDateTime” is best approximation
            workload = ", ".join(item.get("services", []) or [])  # list of services/workloads
            # Filter by since
            if since_dt and last_mod:
                try:
                    ldt = dt.datetime.fromisoformat(last_mod.replace("Z", "+00:00"))
                    if ldt < since_dt:
                        continue
                except Exception:
                    pass
            # Try to infer an official roadmap id/link from title (best effort)
            rid = ""
            ml = ""
            m = _RE_ROADMAP_ID.search(title)
            if m:
                rid = m.group(1)
                ml = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}"
            # Map to Row; Cloud_instance blank -> treat as General downstream
            rows.append(
                Row(
                    PublicId=rid,
                    Title=title,
                    Source="graph",
                    Product_Workload=workload,
                    Status=item.get("status") or "—",
                    LastModified=last_mod,
                    ReleaseDate=rel or "—",
                    Cloud_instance="",  # blank; will be normalized as General for filtering/CSV
                    Official_Roadmap_link=ml,
                    MessageId=f"MC{msg_id}" if msg_id and not msg_id.startswith("MC") else msg_id,
                )
            )
        url = data.get("@odata.nextLink")

    print(f"Graph OK. thumbprint={thumb} rows={len(rows)}")
    return rows


def fetch_fallback_public(since_dt: Optional[dt.datetime]) -> List[Row]:
    """
    Fallback path if Graph is disabled/unavailable. This is intentionally light:
    we return an empty list or a tiny placeholder row (optional).
    If you have an existing public/RSS fetcher in your repo, you can call that here.

    Note: To keep CI deterministic without external calls, we generate zero rows
    by default. Uncomment the sample block below to emit a single placeholder.
    """
    rows: List[Row] = []

    # --- Optional: emit a single placeholder row so your pipeline is never "empty"
    # sample = Row(
    #     PublicId="000000",
    #     Title="(Fallback) Example message",
    #     Source="public",
    #     Product_Workload="Microsoft 365 suite",
    #     Status="—",
    #     LastModified=dt.datetime.now(dt.timezone.utc).isoformat(),
    #     ReleaseDate="—",
    #     Cloud_instance="",  # blank -> treated as General
    #     Official_Roadmap_link="",
    #     MessageId="MC0000000",
    # )
    # rows.append(sample)
    return rows


def write_csv(path: str, rows: List[Row]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for r in rows:
            # Normalize blank/None Cloud_instance to "General" on write
            cloud = "General" if not (r.Cloud_instance or "").strip() else r.Cloud_instance
            w.writerow([
                r.PublicId,
                r.Title,
                r.Source,
                r.Product_Workload,
                r.Status,
                r.LastModified,
                r.ReleaseDate,
                cloud,
                r.Official_Roadmap_link,
                r.MessageId,
            ])


def write_json(path: str, rows: List[Row]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out: List[Dict[str, str]] = []
    for r in rows:
        dd = asdict(r)
        if not (dd.get("Cloud_instance") or "").strip():
            dd["Cloud_instance"] = "General"
        out.append(dd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    cfg = load_config(args.config)

    # Determine cloud filter set
    wanted_clouds: Set[str] = set()
    for c in args.cloud or []:
        wanted_clouds |= normalize_clouds(c)

    # Time filter
    since_dt = _since_from_args(args.since, args.months)

    # Guard: decide whether Graph is usable
    graph_enabled = (not args.no_graph) and HAVE_GRAPH_DEPS and secrets_present(cfg)
    sources_count: Dict[str, int] = {"graph": 0, "public-json": 0, "rss": 0}

    rows_all: List[Row] = []
    errors = 0

    if graph_enabled:
        try:
            g_rows = fetch_graph_messages(cfg, since_dt)
            sources_count["graph"] = len(g_rows)
            rows_all.extend(g_rows)
        except Exception as ex:
            errors += 1
            print(f"WARN: graph-fetch failed: {ex}")
            # fall through to fallback
    else:
        # Helpful logging for empty/missing secrets
        if not HAVE_GRAPH_DEPS:
            print("WARN: graph deps (msal/cryptography) not installed; using fallback.")
        elif args.no_graph:
            print("INFO: --no-graph set; using fallback.")
        else:
            print("WARN: Graph secrets not present or password env missing; using fallback.")

    # Fallback (public/RSS or placeholder)
    try:
        fb_rows = fetch_fallback_public(since_dt)
        # You can split by type and count into 'public-json' vs 'rss' if you want; we keep it simple:
        sources_count["public-json"] += len(fb_rows)
        rows_all.extend(fb_rows)
    except Exception as ex:
        errors += 1
        print(f"WARN: fallback failed: {ex}")

    # De-dup by (MessageId, Title)-ish
    dedup: Dict[Tuple[str, str], Row] = {}
    for r in rows_all:
        key = (r.MessageId or "", r.Title or "")
        if key not in dedup:
            dedup[key] = r
    rows_all = list(dedup.values())

    # Filter by cloud
    if wanted_clouds:
        rows_all = [r for r in rows_all if include_by_cloud(r.Cloud_instance, wanted_clouds)]

    # Filter by since if not already applied
    if since_dt:
        def _ok(last_mod: str) -> bool:
            try:
                lm = dt.datetime.fromisoformat(last_mod.replace("Z", "+00:00"))
                return lm >= since_dt
            except Exception:
                return True  # keep items we cannot parse safely
        rows_all = [r for r in rows_all if _ok(r.LastModified or "")]

    # Emit
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    if args.emit == "csv":
        write_csv(args.out, rows_all)
    else:
        write_json(args.out, rows_all)

    # Stats
    stats = {
        "rows_total": len(rows_all),
        "sources": sources_count,
        "errors": errors,
        "cloud_filter": sorted(list(wanted_clouds)),
        "since": since_dt.isoformat() if since_dt else None,
        "emit": args.emit,
        "out": args.out,
    }
    if args.stats_out:
        with open(args.stats_out, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)

    # Always print a concise summary line (handy in CI logs)
    print(
        f"Done. rows={stats['rows_total']} "
        f"sources={stats['sources']} "
        f"errors={errors}"
    )


if __name__ == "__main__":
    main()
