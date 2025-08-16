#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# External deps expected in the runner (as in your workflow):
#   msal, requests, cryptography
import requests
import msal
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates


# ----------------------------
# Model & constants
# ----------------------------

FIELD_ORDER: List[str] = [
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

RE_ID = re.compile(r"\b(\d{5,6})\b")
RE_ID_VERBOSE = re.compile(r"Roadmap\s*ID[:\s]*([0-9]{5,6})", re.I)

GRAPH_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_BASE = "https://graph.microsoft.com"
GRAPH_ENDPOINT = "/beta/admin/serviceAnnouncement/messages?$top=200"


@dataclass
class Row:
    PublicId: str = ""
    Title: str = ""
    Source: str = ""  # "graph", "public-json", "rss", "seed"
    Product_Workload: str = ""
    Status: str = ""
    LastModified: str = ""
    ReleaseDate: str = ""
    Cloud_instance: str = ""
    Official_Roadmap_link: str = ""
    MessageId: str = ""


# ----------------------------
# Utilities
# ----------------------------

def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", help="graph_config.json path", default="graph_config.json")
    p.add_argument("--since", help="YYYY-MM-DD", default="")
    p.add_argument("--months", help="N months back", default="")
    p.add_argument("--cloud", action="append", default=[], help="Cloud label; repeatable")
    p.add_argument("--no-graph", action="store_true", help="Skip Graph (fallback only)")
    p.add_argument("--seed-ids", default="", help="Comma/space/pipe-separated PublicIds to include")
    p.add_argument("--emit", choices=["csv", "json"], required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--stats-out", default="")
    return p.parse_args(argv)


def _read_cfg(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _b64_to_cert_dict(pfx_b64: str, password: str) -> Dict[str, str]:
    """Decode base64 PFX → msal cert dict {'thumbprint','private_key','public_certificate'}."""
    data = base64.b64decode(pfx_b64)
    key, cert, addl = load_key_and_certificates(data, password.encode("utf-8"))
    if cert is None or key is None:
        raise ValueError("PFX missing key or cert")

    # PEM
    pub_pem = cert.public_bytes(Encoding.PEM).decode("utf-8")
    priv_pem = key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    ).decode("utf-8")

    # Thumbprint (SHA1 upper-hex)
    der = cert.public_bytes(Encoding.DER)
    sha1 = hashes.Hash(hashes.SHA1())
    sha1.update(der)
    thumb = sha1.finalize().hex().upper()
    return {"thumbprint": thumb, "private_key": priv_pem, "public_certificate": pub_pem}


def _when_from_flags(since: str, months: str) -> Optional[datetime]:
    if since:
        return datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    if months:
        try:
            m = int(months)
            return datetime.now(timezone.utc) - timedelta(days=30 * m)
        except Exception:
            return None
    return None


def _extract_public_id(msg: Dict[str, Any]) -> str:
    # Prefer explicit hint in body or links
    body = (msg.get("body", {}) or {}).get("content", "") or ""
    link = msg.get("externalLink", "") or ""
    for txt in (link, body):
        m = RE_ID_VERBOSE.search(txt) or RE_ID.search(txt)
        if m:
            return m.group(1)
    return ""


def _official_link(public_id: str) -> str:
    if not public_id:
        return ""
    return f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={public_id}"


def _write_csv(path: str | Path, rows: List[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELD_ORDER)
        w.writeheader()
        for r in rows:
            w.writerow({k: asdict(r).get(k, "") for k in FIELD_ORDER})


def _write_json(path: str | Path, rows: List[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        payload = [{k: asdict(r).get(k, "") for k in FIELD_ORDER} for r in rows]
        json.dump(payload, f, indent=2)


def _save_stats(path: str | Path, stats: Dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def _split_ids(s: str) -> List[str]:
    if not s:
        return []
    # allow comma/pipe/space
    parts = re.split(r"[,\s|]+", s.strip())
    return [p for p in parts if p]


# ----------------------------
# Graph fetch
# ----------------------------

def _try_fetch_graph(cfg: Dict[str, Any], since_dt: Optional[datetime]) -> Tuple[List[Row], Optional[str]]:
    tenant = (cfg.get("TENANT") or cfg.get("tenant") or "").strip()
    client = (cfg.get("CLIENT") or cfg.get("client") or "").strip()
    pfx_b64 = (cfg.get("PFX_B64") or cfg.get("pfx_base64") or "").strip()
    pw = os.environ.get(cfg.get("M365_PFX_PASSWORD", "M365_PFX_PASSWORD"), "")

    if not tenant or not client or not pfx_b64 or not pw:
        return [], "Graph client not available on this runner"

    try:
        cred = _b64_to_cert_dict(pfx_b64, pw)
    except Exception as e:
        return [], f"PFX/token error: {e}"

    app = msal.ConfidentialClientApplication(
        client_id=client,
        authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=cred,
    )

    token = app.acquire_token_for_client(scopes=[GRAPH_SCOPE])
    if "access_token" not in token:
        return [], f"Token failure: {token.get('error_description','unknown')}"

    headers = {"Authorization": f"Bearer {token['access_token']}"}
    url = GRAPH_BASE + GRAPH_ENDPOINT
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [], f"Graph GET failed: {e}"

    items = data.get("value", []) if isinstance(data, dict) else []
    rows: List[Row] = []

    for m in items:
        # Optional server-side time filter if supplied
        lm = (m.get("lastModifiedDateTime") or "").strip()
        if since_dt and lm:
            try:
                lm_dt = datetime.fromisoformat(lm.replace("Z", "+00:00"))
                if lm_dt < since_dt:
                    continue
            except Exception:
                pass

        public_id = _extract_public_id(m)
        title = (m.get("title") or "").strip()
        prod = ",".join(m.get("services", []) or [])  # e.g. ["Microsoft Teams"]
        msg_id = (m.get("id") or "").strip()
        roadmap_link = _official_link(public_id)

        rows.append(
            Row(
                PublicId=public_id,
                Title=title,
                Source="graph",
                Product_Workload=prod,
                Status=(m.get("category") or "").strip(),  # not perfect; placeholder
                LastModified=lm,
                ReleaseDate="",  # not provided by API; left blank
                Cloud_instance="",  # not provided; blank → shown as em dash in UI
                Official_Roadmap_link=roadmap_link,
                MessageId=msg_id,
            )
        )

    return rows, None


# ----------------------------
# Main
# ----------------------------

def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    cfg = _read_cfg(args.config)

    # Time window
    since_dt = _when_from_flags(args.since, args.months)

    # Seed rows (forced ids just to ensure something is there if Graph off)
    seed_rows: List[Row] = []
    for sid in _split_ids(args.seed_ids):
        seed_rows.append(
            Row(
                PublicId=sid,
                Title=f"[{sid}]",
                Source="seed",
                Official_Roadmap_link=_official_link(sid),
            )
        )

    # Graph (unless explicitly disabled)
    rows: List[Row] = []
    errors: int = 0
    sources = {"graph": 0, "public-json": 0, "rss": 0, "seed": 0}

    if not args.no_graph:
        g_rows, g_err = _try_fetch_graph(cfg, since_dt)
        if g_err:
            print(f"WARN: {g_err}")
            errors += 1
        else:
            rows.extend(g_rows)
            sources["graph"] += len(g_rows)
    else:
        print("INFO: --no-graph; skipping Graph fetch")

    # Add seeds last (low-priority placeholder)
    if seed_rows:
        rows.extend(seed_rows)
        sources["seed"] += len(seed_rows)

    # Simple cloud filter is performed later in generate_report; here we just save master.

    # Sort newest first by LastModified when present
    def _key(r: Row) -> Tuple[int, str]:
        try:
            return (0, datetime.fromisoformat((r.LastModified or "").replace("Z", "+00:00")).isoformat())
        except Exception:
            return (1, "")
    rows.sort(key=_key, reverse=True)

    stats = {
        "rows": len(rows),
        "sources": sources,
        "errors": errors,
    }

    if args.emit == "csv":
        _write_csv(args.out, rows)
        if args.stats_out:
            _save_stats(args.stats_out, stats)
    else:
        _write_json(args.out, rows)
        if args.stats_out:
            _save_stats(args.stats_out, stats)

    print(f"Done. rows={len(rows)} sources={json.dumps(sources)} errors={errors}")
    # Optional file list (handy in CI)
    outdir = Path(args.out).parent
    try:
        names = sorted([p.name for p in outdir.iterdir()])
        print(f"DEBUG: files in {outdir}: {names}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
