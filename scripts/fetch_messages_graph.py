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
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Sequence

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from msal import ConfidentialClientApplication

try:
    from bs4 import BeautifulSoup  # present in CI
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

# ---------- CLI ----------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch roadmap/MC data from Graph (with fallbacks).")
    p.add_argument("--config", default="graph_config.json", help="JSON config with Graph credentials (optional).")
    p.add_argument("--since", default="", help="Only include items on/after YYYY-MM-DD (MC lastModifiedDateTime).")
    p.add_argument("--months", default="", help="Only include items within last N months (MC lastModifiedDateTime).")
    p.add_argument("--cloud", action="append", default=[], help="Cloud(s) to include (informational for fetch).")
    p.add_argument("--no-graph", action="store_true", help="Skip Graph completely (fallback only).")
    p.add_argument("--seed-ids", default="", help="Comma-separated Roadmap IDs to seed when graph is unavailable.")
    p.add_argument("--emit", choices=["csv", "json"], required=True, help="Output format.")
    p.add_argument("--out", required=True, help="Output path.")
    p.add_argument("--stats-out", default="", help="Optional JSON stats path.")
    return p.parse_args(argv)


# ---------- Model & constants ----------

EMDASH = "—"

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
    # MC enrichment
    "MC_Body",
    "MC_Published",
    "MC_LastUpdated",
    "MC_Services",
    "MC_Platforms",
    "MC_Tags",
    "MC_Relevance",
]


@dataclass
class Row:
    PublicId: str = ""
    Title: str = ""
    Source: str = ""
    Product_Workload: str = ""
    Status: str = ""
    LastModified: str = ""
    ReleaseDate: str = ""
    Cloud_instance: str = ""
    Official_Roadmap_link: str = ""
    MessageId: str = ""
    MC_Body: str = ""
    MC_Published: str = ""
    MC_LastUpdated: str = ""
    MC_Services: str = ""
    MC_Platforms: str = ""
    MC_Tags: str = ""
    MC_Relevance: str = ""


# ---------- Config & credentials ----------


def _load_cfg(path: str) -> dict:
    """
    Accepts many key spellings to be forgiving with your workflow step:

    TENANT | tenant | tenant_id
    CLIENT | client | client_id
    PFX_B64 | pfx_base64
    M365_PFX_PASSWORD | pfx_password_env (env-var name)
    """
    cfg: dict = {}
    try:
        if path and Path(path).is_file():
            cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        print(f"WARN: failed to read config: {e}", file=sys.stderr)

    # normalize-ish access
    def g(*names: str) -> str:
        for n in names:
            for k, v in cfg.items():
                if k.lower() == n.lower():
                    return v
        return ""

    # expose in canonical keys we use below
    return {
        "tenant": g("TENANT", "tenant", "tenant_id"),
        "client": g("CLIENT", "client", "client_id"),
        "pfx_b64": g("PFX_B64", "pfx_base64"),
        "pfx_password_env": g("M365_PFX_PASSWORD", "pfx_password_env") or "M365_PFX_PASSWORD",
    }


def _load_pfx_from_b64(b64: str, password: str) -> tuple[bytes, bytes, str]:
    """
    Return (private_key_pem, public_cert_pem, sha1_thumbprint_hex).
    Raises with a friendly message if anything fails.
    """
    try:
        raw = base64.b64decode(b64.encode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"PFX base64 decode failed: {e}") from e

    try:
        key, cert, _chain = pkcs12.load_key_and_certificates(
            raw, password.encode("utf-8") if password else None
        )
        if not key or not cert:
            raise RuntimeError("PFX did not contain key+cert")
        pk_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        thumb = cert.fingerprint(hashes.SHA1()).hex()
        return pk_pem, cert_pem, thumb
    except Exception as e:
        raise RuntimeError(f"PFX load failed: {e}") from e


def _acquire_graph_token(tenant: str, client: str, pfx_b64: str, pw: str) -> str:
    pk_pem, cert_pem, thumb = _load_pfx_from_b64(pfx_b64, pw)
    cred = {
        "private_key": pk_pem.decode("utf-8"),
        "thumbprint": thumb,
        "public_certificate": cert_pem.decode("utf-8"),
    }
    authority = f"https://login.microsoftonline.com/{tenant}"
    app = ConfidentialClientApplication(client_id=client, authority=authority, client_credential=cred)
    scope = ["https://graph.microsoft.com/.default"]
    tok = app.acquire_token_for_client(scopes=scope)
    if "access_token" not in tok:
        raise RuntimeError(f"Token acquisition failed: {tok.get('error_description') or tok}")
    return tok["access_token"]


# ---------- Graph fetch ----------


def _parse_dt_filter(since: str, months: str) -> str | None:
    if since:
        try:
            d = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc)
        except Exception:
            return None
        return d.isoformat().replace("+00:00", "Z")
    if months:
        try:
            n = int(months)
        except Exception:
            return None
        d = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * max(n, 0))
        return d.isoformat().replace("+00:00", "Z")
    return None


_RE_NUM = re.compile(r"\b(\d{4,7})\b")
_RE_ROADMAP = re.compile(
    r"(?:roadmap\s*id\s*[:#]?\s*|\?filters=.*?&searchterms=)(\d{4,7})",
    re.IGNORECASE,
)


def _extract_roadmap_ids(html_body: str) -> list[str]:
    """
    Try hard to find roadmap ids in MC content (links or plain text).
    """
    text = html_body or ""
    if BeautifulSoup and "<" in text and ">" in text:
        try:
            soup = BeautifulSoup(text, "html.parser")
            # include anchor hrefs
            hrefs = " ".join(a.get("href", "") for a in soup.find_all("a"))
            blob = " ".join([soup.get_text(separator=" "), hrefs])
        except Exception:
            blob = text
    else:
        blob = text

    ids = set(_RE_ROADMAP.findall(blob))
    if not ids:
        # last resort: any 5-7 digit number next to 'roadmap'
        if "roadmap" in blob.lower():
            ids.update(_RE_NUM.findall(blob))
    return sorted(ids)


def _call_graph_messages(token: str, since_iso: str | None) -> list[dict]:
    """
    Pull all MC messages; filter server-side by lastModifiedDateTime when possible.
    """
    base = "https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/messages"
    params = {"$top": "50"}
    if since_iso:
        params["$filter"] = f"lastModifiedDateTime ge {since_iso}"

    items: list[dict] = []
    url = base
    while True:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params if url == base else None, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Graph GET failed {resp.status_code}: {resp.text}")
        data = resp.json()
        items.extend(data.get("value", []))
        next_link = data.get("@odata.nextLink")
        if not next_link:
            break
        url = next_link
    return items


def _rows_from_graph(items: list[dict]) -> list[Row]:
    out: list[Row] = []
    for m in items:
        mid = (m.get("id") or "").strip()
        title = (m.get("title") or "").strip()
        sev = (m.get("severity") or "").strip()  # “informational”, “normal”, “high”
        lastmod = (m.get("lastModifiedDateTime") or "").strip()
        published = (m.get("startDateTime") or "").strip()  # closest to “published”
        services = " / ".join(m.get("services") or [])
        tags = " / ".join(m.get("tags") or [])
        # Some tenants expose platforms; many don't. Keep optional.
        platforms = " / ".join(m.get("platforms") or []) if isinstance(m.get("platforms"), list) else ""

        body_html = ""
        b = m.get("body") or {}
        if isinstance(b, dict):
            body_html = (b.get("content") or "").strip()

        ids = _extract_roadmap_ids(body_html)
        if not ids:
            # No roadmap id discovered: still include as a blank-id row so you can see it,
            # or skip if you prefer. We'll include it with PublicId "" so renderer can ignore if needed.
            ids = [""]

        for rid in ids:
            out.append(
                Row(
                    PublicId=rid,
                    Title=title or (f"[{rid}]" if rid else "[Roadmap item]"),
                    Source="graph",
                    Product_Workload=services,
                    Status="",  # not exposed by MC API
                    LastModified=lastmod,
                    ReleaseDate="",  # not exposed by MC API
                    Cloud_instance="",  # MC items are tenant-agnostic; leave blank
                    Official_Roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={rid}" if rid else "",
                    MessageId=mid,
                    MC_Body=body_html,
                    MC_Published=published,
                    MC_LastUpdated=lastmod,
                    MC_Services=services,
                    MC_Platforms=platforms,
                    MC_Tags=tags,
                    MC_Relevance=sev,
                )
            )
    return out


# ---------- Fallbacks ----------


def _rows_from_seed(seed_ids: Iterable[str]) -> list[Row]:
    out: list[Row] = []
    for s in seed_ids:
        s = (s or "").strip()
        if not s:
            continue
        out.append(
            Row(
                PublicId=s,
                Title=f"[{s}]",
                Source="seed",
                Product_Workload="",
                Status="",
                LastModified="",
                ReleaseDate="",
                Cloud_instance="",
                Official_Roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={s}",
                MessageId="",
            )
        )
    return out


def _split_csv_like(s: str) -> list[str]:
    if not s:
        return []
    parts = re.split(r"[,\s]+", s)
    return [p.strip() for p in parts if p.strip()]


# ---------- Writers ----------


def write_csv(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELD_ORDER)
        w.writeheader()
        for r in rows:
            w.writerow({k: asdict(r).get(k, "") for k in FIELD_ORDER})


def write_json(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump([{k: asdict(r).get(k, "") for k in FIELD_ORDER}], f, indent=2)


# ---------- MAIN ----------


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    cfg = _load_cfg(args.config)
    since_iso = _parse_dt_filter(args.since, args.months)

    rows: list[Row] = []
    sources = {"graph": 0, "public-json": 0, "rss": 0, "seed": 0}
    errors = 0

    # Try Graph unless explicitly disabled
    if not args.no_graph:
        tenant = cfg.get("tenant") or ""
        client = cfg.get("client") or ""
        pfx_b64 = cfg.get("pfx_b64") or ""
        pw_env = cfg.get("pfx_password_env") or "M365_PFX_PASSWORD"
        pfx_pw = os.environ.get(pw_env, "")

        have_creds = all([tenant, client, pfx_b64, pfx_pw])
        if not have_creds:
            print("INFO: Graph credentials missing/invalid → using public fallback only (as if --no-graph).")
        else:
            try:
                token = _acquire_graph_token(tenant, client, pfx_b64, pfx_pw)
                items = _call_graph_messages(token, since_iso)
                g_rows = _rows_from_graph(items)
                rows.extend(g_rows)
                sources["graph"] = len(g_rows)
            except Exception as e:
                errors += 1
                print(f"WARN: graph-fetch failed: {e}")
    else:
        print("INFO: --no-graph enabled; skipping Graph fetch.")

    # Seed fallback (optional)
    seed_rows = _rows_from_seed(_split_csv_like(args.seed_ids))
    if seed_rows:
        rows.extend(seed_rows)
        sources["seed"] = len(seed_rows)

    # Deduplicate: if the same PublicId appears multiple times from different MC posts, keep first
    seen = set()
    deduped: list[Row] = []
    for r in rows:
        key = (r.PublicId or "", r.MessageId or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    rows = deduped

    # Write outputs
    if args.emit == "csv":
        write_csv(args.out, rows)
    else:
        write_json(args.out, rows)

    # Stats (optional)
    stats = {
        "generated_utc": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": sources,
        "errors": errors,
        "row_count": len(rows),
        "filters": {"since": args.since, "months": args.months, "cloud": args.cloud},
    }
    if args.stats_out:
        Path(args.stats_out).write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(
        f"Done. rows={len(rows)} sources={sources} errors={errors}"
    )
    # Debug: list files in output dir if caller used ./output
    try:
        outdir = Path(args.out).parent
        files = sorted([p.name for p in outdir.iterdir()]) if outdir.exists() else []
        print(f"DEBUG: files in {outdir}: {files}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
