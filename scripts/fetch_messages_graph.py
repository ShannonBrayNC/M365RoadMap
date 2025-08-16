#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence, Tuple

# Optional deps
try:
    import msal  # type: ignore
except Exception:  # pragma: no cover
    msal = None  # type: ignore

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# Optional public fallbacks
try:
    import feedparser  # type: ignore
except Exception:  # pragma: no cover
    feedparser = None  # type: ignore

try:
    from cryptography.hazmat.primitives.serialization import pkcs12  # type: ignore
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    from cryptography.hazmat.primitives import hashes
except Exception:  # pragma: no cover
    pkcs12 = None  # type: ignore


# ---------- Schema ----------

CSV_FIELDS = [
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


@dataclass
class Row:
    PublicId: str
    Title: str = ""
    Source: str = ""
    Product_Workload: str = ""
    Status: str = ""
    LastModified: str = ""
    ReleaseDate: str = ""
    Cloud_instance: str = ""
    Official_Roadmap_link: str = ""
    MessageId: str = ""

    @classmethod
    def from_public_id(cls, pid: str, *, source: str = "seed") -> "Row":
        pid = str(pid).strip()
        return cls(
            PublicId=pid,
            Title=f"[{pid}]",
            Source=source,
            Official_Roadmap_link=_roadmap_link(pid),
        )

    def to_dict(self) -> dict[str, str]:
        d = asdict(self)
        # Ensure keys in the expected order
        return {k: d.get(k, "") or "" for k in CSV_FIELDS}


# ---------- Utils ----------

_RE_NUM = re.compile(r"\b(\d{4,})\b")  # Roadmap IDs: 4+ digits

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _roadmap_link(pid: str) -> str:
    return f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pid}"


def _split_csv_like(s: str | None) -> list[str]:
    if not s:
        return []
    # Accept comma/pipe/space separated
    raw = re.split(r"[,\|\s]+", s)
    return [t for t in (x.strip() for x in raw) if t]


def _human_clouds(clouds: Sequence[str] | None) -> str:
    if not clouds:
        return "General"
    # Show first or "Multiple"
    uniq = []
    seen = set()
    for c in clouds:
        cc = (c or "").strip()
        if cc and cc not in seen:
            seen.add(cc)
            uniq.append(cc)
    if not uniq:
        return "General"
    return uniq[0] if len(uniq) == 1 else "Multiple"


def _write_csv(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r.to_dict())


def _write_json(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in rows], f, indent=2)


def _write_stats(path: str | Path, stats: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)


def _list_output_dir() -> list[str]:
    out = []
    op = Path("output")
    if op.exists():
        for child in sorted(op.iterdir()):
            out.append(child.name)
    return out


# ---------- Config ----------

def _load_config(path: str | Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return cfg
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # Accept both upper and lower keys
        cfg["tenant"] = (data.get("TENANT") or data.get("tenant") or data.get("tenant_id") or "").strip()
        cfg["client"] = (data.get("CLIENT") or data.get("client") or data.get("client_id") or "").strip()
        cfg["pfx_b64"] = (data.get("PFX_B64") or data.get("pfx_b64") or data.get("pfx_base64") or "").strip()
        cfg["pfx_password_env"] = (data.get("PFX_PASSWORD_ENV") or data.get("M365_PFX_PASSWORD") or "M365_PFX_PASSWORD").strip()
        cfg["public_json_url"] = (data.get("public_json_url") or "").strip()
        cfg["public_rss_url"] = (data.get("public_rss_url") or "").strip()
        # Optional authority/graph base (defaults used if absent)
        cfg["authority_base"] = (data.get("authority_base") or "https://login.microsoftonline.com").strip()
        cfg["graph_base"] = (data.get("graph_base") or "https://graph.microsoft.com").strip()
    except Exception:
        pass
    return cfg


# ---------- Graph ----------

def _pfx_to_key_thumb(
    pfx_b64: str, password: str
) -> Tuple[str, str]:
    """
    Decode PFX base64 and return (private_key_pem, thumbprint_hex_lower).
    """
    if not pkcs12:
        raise RuntimeError("cryptography is not available to decode PFX")

    raw = base64.b64decode(pfx_b64)
    try:
        key, cert, _ = pkcs12.load_key_and_certificates(raw, password.encode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"PFX load failed: {e}")

    if key is None or cert is None:
        raise RuntimeError("PFX does not contain both private key and certificate")

    # Export private key to PEM (no password)
    try:
        pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        private_key_pem = pem.decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Private key export failed: {e}")

    # Compute SHA1 thumbprint of DER cert (lowercase hex)
    der = cert.public_bytes(Encoding.DER)
    digest = hashes.Hash(hashes.SHA1())
    digest.update(der)
    thumb = digest.finalize().hex()
    return private_key_pem, thumb


def _graph_token_with_pfx(
    *, tenant: str, client: str, pfx_b64: str, pfx_password: str, authority_base: str, scope_base: str
) -> str:
    if msal is None:
        raise RuntimeError("MSAL not installed")

    private_key, thumb = _pfx_to_key_thumb(pfx_b64, pfx_password)

    authority = f"{authority_base.rstrip('/')}/{tenant}"
    app = msal.ConfidentialClientApplication(
        client_id=client,
        authority=authority,
        client_credential={"private_key": private_key, "thumbprint": thumb},
    )
    scopes = [f"{scope_base.rstrip('/')}/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    if "access_token" not in result:
        raise RuntimeError(f"Token acquisition failed: {result.get('error_description') or result}")
    return result["access_token"]  # type: ignore[return-value]


def _fetch_graph_rows(
    *, tenant: str, client: str, pfx_b64: str, pfx_password: str, authority_base: str, graph_base: str, since_iso: str | None
) -> tuple[list[Row], str | None]:
    """
    Query MC messages and emit a Row per roadmapId found on each message.
    """
    if requests is None:
        return [], "requests not available"

    try:
        token = _graph_token_with_pfx(
            tenant=tenant,
            client=client,
            pfx_b64=pfx_b64,
            pfx_password=pfx_password,
            authority_base=authority_base,
            scope_base=graph_base,
        )
    except Exception as e:
        return [], f"PFX/token error: {e}"

    headers = {"Authorization": f"Bearer {token}"}
    # We keep it simple: pull the admin announcements messages (MC)
    url = f"{graph_base.rstrip('/')}/v1.0/admin/serviceAnnouncement/messages?$top=500"
    if since_iso:
        # Filter on lastModifiedDateTime if provided
        url += f"&$filter=lastModifiedDateTime ge {since_iso}"

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code >= 400:
            return [], f"Graph call failed: HTTP {resp.status_code} - {resp.text[:400]}"
        data = resp.json()
    except Exception as e:
        return [], f"Graph request error: {e}"

    rows: list[Row] = []
    for item in data.get("value", []):
        # Expect fields like: id (MC...), title, services[], lastModifiedDateTime, roadmapIds[]
        message_id = str(item.get("id", "") or "")
        title = str(item.get("title", "") or "")
        last_mod = str(item.get("lastModifiedDateTime", "") or "")
        services = item.get("services") or []
        workloads = "/".join(s for s in services if s)
        roadmap_ids = item.get("roadmapIds") or []

        # If roadmapIds is missing, try to sniff numbers from title/body
        if not roadmap_ids:
            candidates = set(_RE_NUM.findall(title))
            body = ""
            try:
                b = (item.get("body") or {}).get("content") or ""
                body = str(b)
            except Exception:
                pass
            candidates.update(_RE_NUM.findall(body))
            roadmap_ids = sorted(candidates)

        for pid in roadmap_ids:
            r = Row(
                PublicId=str(pid),
                Title=title or f"[{pid}]",
                Source="graph",
                Product_Workload=workloads,
                Status="",
                LastModified=last_mod.replace("Z", "").replace("z", ""),
                ReleaseDate="",
                Cloud_instance="",  # keep empty to pass 'General' default in report
                Official_Roadmap_link=_roadmap_link(str(pid)),
                MessageId=message_id,
            )
            rows.append(r)

    return rows, None


# ---------- Public fallbacks (optional) ----------

def _fetch_public_json(url: str) -> list[Row]:
    """
    Very best-effort: expects an array with items containing an 'id' or detectable digits.
    """
    if not url or requests is None:
        return []
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    rows: list[Row] = []
    if isinstance(data, list):
        for item in data:
            # Try 'id' or scan string fields for digits
            pid = None
            if isinstance(item, dict):
                for key in ("id", "Id", "publicId", "PublicId", "roadmapId"):
                    if key in item:
                        pid = str(item[key])
                        break
                if not pid:
                    # scan dict values
                    for v in item.values():
                        if isinstance(v, str):
                            m = _RE_NUM.search(v)
                            if m:
                                pid = m.group(1)
                                break
            if pid:
                rows.append(Row.from_public_id(pid, source="public-json"))
    return rows


def _fetch_public_rss(url: str) -> list[Row]:
    """Extract roadmap IDs from titles in an RSS/Atom feed."""
    if not url or feedparser is None:
        return []
    try:
        feed = feedparser.parse(url)  # type: ignore
    except Exception:
        return []
    rows: list[Row] = []
    for entry in getattr(feed, "entries", []):
        title = getattr(entry, "title", "") or ""
        for pid in _RE_NUM.findall(title):
            r = Row.from_public_id(pid, source="rss")
            r.Title = title or r.Title
            rows.append(r)
    return rows


# ---------- Main pipeline ----------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fetch Microsoft 365 roadmap rows (Graph first → fallbacks), emit CSV/JSON."
    )
    p.add_argument("--config", help="Path to graph_config.json", default="graph_config.json")
    p.add_argument("--since", help="Only include items on/after YYYY-MM-DD", default="")
    p.add_argument("--months", help="Only include items within last N months", default="")
    p.add_argument("--cloud", action="append", help="Cloud filter label (repeatable)", default=[])
    p.add_argument("--no-graph", action="store_true", help="Skip Graph (fallback-only)")
    p.add_argument("--seed-ids", help="Comma/pipe/space separated roadmap IDs to include as rows", default="")
    p.add_argument("--emit", required=True, choices=["csv", "json"], help="Output format")
    p.add_argument("--out", required=True, help="Output file path")
    p.add_argument("--stats-out", help="Optional JSON stats path", default="")
    return p


def _apply_since_months_filter(rows: list[Row], since: str, months: str) -> list[Row]:
    """Currently a passthrough (date lives on MC not roadmap). Hook left in for future rules."""
    # If you later map ReleaseDate/LastModified to real dates, filter here.
    return rows


def main() -> None:
    ap = _build_arg_parser()
    args = ap.parse_args()

    cfg = _load_config(args.config)

    # Inputs summary
    human_cloud = _human_clouds(args.cloud or ["General"])
    print(
        f"Running fetch_messages_graph.py with: --config {args.config}  --cloud {human_cloud} ",
        flush=True,
    )

    stats: dict[str, Any] = {
        "when_utc": _now_utc_iso(),
        "clouds": args.cloud or ["General"],
        "sources": {"graph": 0, "public-json": 0, "rss": 0, "seed": 0},
        "errors": 0,
        "notes": [],
    }

    since_iso = ""
    if args.since:
        try:
            dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            since_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    elif args.months:
        try:
            n = int(args.months)
            dt = datetime.now(timezone.utc) - timedelta(days=30 * n)
            since_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    rows: list[Row] = []
    errors = 0

    # 1) Graph (unless --no-graph)
    graph_err: str | None = None
    if not args.no-graph if False else not args.no_graph:  # guard for linters
        pass
    if not args.no_graph:
        tenant = cfg.get("tenant", "")
        client = cfg.get("client", "")
        pfx_b64 = cfg.get("pfx_b64", "")
        pw_env = cfg.get("pfx_password_env", "M365_PFX_PASSWORD")
        pfx_pass = os.environ.get(pw_env, "")
        authority_base = cfg.get("authority_base", "https://login.microsoftonline.com")
        graph_base = cfg.get("graph_base", "https://graph.microsoft.com")

        if not (msal and requests and tenant and client and pfx_b64 and pfx_pass):
            graph_err = "Graph client not available on this runner"
        else:
            g_rows, graph_err = _fetch_graph_rows(
                tenant=tenant,
                client=client,
                pfx_b64=pfx_b64,
                pfx_password=pfx_pass,
                authority_base=authority_base,
                graph_base=graph_base,
                since_iso=since_iso or None,
            )
            if not graph_err and g_rows:
                rows.extend(g_rows)
                stats["sources"]["graph"] = len(g_rows)

    if graph_err:
        print(f"WARN: graph-fetch failed: {graph_err}", flush=True)
        errors += 1

    # 2) Public fallbacks (optional, only if Graph yielded nothing)
    if not rows:
        pj = cfg.get("public_json_url", "")
        pr = cfg.get("public_rss_url", "")

        if pj:
            pub_rows = _fetch_public_json(pj)
            if pub_rows:
                rows.extend(pub_rows)
                stats["sources"]["public-json"] = len(pub_rows)

        if pr and not rows:
            rss_rows = _fetch_public_rss(pr)
            if rss_rows:
                rows.extend(rss_rows)
                stats["sources"]["rss"] = len(rss_rows)

    # 3) Seed IDs (always permitted to enrich/force)
    seed = _split_csv_like(args.seed_ids)
    if seed:
        for pid in seed:
            rows.append(Row.from_public_id(pid, source="seed"))
        stats["sources"]["seed"] = stats["sources"].get("seed", 0) + len(seed)

    # Apply optional date filter hook (currently passthrough)
    rows = _apply_since_months_filter(rows, args.since, args.months)

    # Deduplicate by (PublicId, Source, MessageId) to avoid obvious dupes
    dedup: dict[tuple[str, str, str], Row] = {}
    for r in rows:
        key = (r.PublicId, r.Source or "", r.MessageId or "")
        dedup[key] = r
    rows = list(dedup.values())

    # Sort by PublicId (numeric when possible), then by MessageId for stability
    def _key(r: Row) -> tuple[int, str]:
        try:
            return (int(r.PublicId), r.MessageId or "")
        except Exception:
            return (10**12, r.MessageId or "")

    rows.sort(key=_key)

    # Emit
    if args.emit == "csv":
        _write_csv(args.out, rows)
    else:
        _write_json(args.out, rows)

    if args.stats_out:
        stats["errors"] = errors
        stats["row_count"] = len(rows)
        _write_stats(args.stats_out, stats)

    print(
        f"Done. rows={len(rows)} sources={json.dumps(stats['sources'])} errors={errors}",
        flush=True,
    )
    print(f"DEBUG: files in output: { _list_output_dir() }", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
