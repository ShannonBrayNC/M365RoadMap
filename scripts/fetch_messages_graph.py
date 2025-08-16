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
from typing import Iterable, Sequence

import requests
import msal
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
from cryptography.hazmat.primitives import hashes

# -----------------------------
# Constants / helpers
# -----------------------------

# Canonical cloud labels used in CSV/JSON so downstream filters stay stable.
CLOUD_CANON = {
    "Worldwide (Standard Multi-Tenant)": "General",
    "Worldwide": "General",
    "General": "General",
    "GCC": "GCC",
    "GCC High": "GCC High",
    "DoD": "DoD",
}

# CSV/JSON field order
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

RE_ROADMAP_ID = re.compile(r"\[(\d{5,7})\]")  # e.g., "[483355]"
RE_ANY_ID = re.compile(r"\b(\d{5,7})\b")


@dataclass
class Row:
    PublicId: str
    Title: str
    Source: str  # "graph", "public-json", "rss", "seed"
    Product_Workload: str
    Status: str
    LastModified: str  # ISO date or empty
    ReleaseDate: str   # ISO date or empty
    Cloud_instance: str  # General|GCC|GCC High|DoD|"" (unknown)
    Official_Roadmap_link: str
    MessageId: str


# -----------------------------
# Cloud + date utilities
# -----------------------------

def normalize_clouds(inp: str | Sequence[str] | None) -> set[str]:
    """
    Accept a single cloud label or a sequence of labels and return a set of
    canonical labels: {"General", "GCC", "GCC High", "DoD"}.
    """
    out: set[str] = set()
    if not inp:
        return out
    if isinstance(inp, str):
        items = [i.strip() for i in inp.split(",") if i.strip()]
    else:
        # flatten sequence (which could include comma-joined items)
        items: list[str] = []
        for x in inp:
            items.extend([i.strip() for i in str(x).split(",") if i.strip()])
    for raw in items:
        out.add(CLOUD_CANON.get(raw, raw))
    return out


def include_by_cloud(row: Row, selected: set[str]) -> bool:
    """
    Include row if selected is empty (no filtering) or if row.Cloud_instance
    is blank (treated as General/unknown) or matches any selected cloud.
    """
    if not selected:
        return True
    if not row.Cloud_instance:
        # Treat unknown cloud as General; include when General selected
        return "General" in selected
    return row.Cloud_instance in selected


def parse_date_soft(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # Accept YYYY-MM-DD or full ISO
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def within_window(dt_s: str | None, since: str | None, months: str | None) -> bool:
    """
    True if date string dt_s is within the provided window.
    If both since and months are empty, returns True.
    """
    if not since and not months:
        return True
    dts = parse_date_soft(dt_s)
    if dts is None:
        return False  # if caller asked for a window and there is no date, exclude
    if since:
        sdt = parse_date_soft(since)
        if sdt and dts < sdt:
            return False
    if months:
        try:
            m = int(months)
            cutoff = datetime.now(timezone.utc) - timedelta(days=30 * m)
            if dts < cutoff:
                return False
        except ValueError:
            pass
    return True


def _split_csv_like(s: str) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"[,\|;]", s)]
    return [p for p in parts if p]


# -----------------------------
# Graph helpers
# -----------------------------

def _load_msal_client_credential_from_pfx_b64(pfx_b64: str, pfx_password: str | None) -> dict[str, str]:
    """Convert base64 PFX + password into MSAL client_credential dict."""
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

        thumb_hex = cert.fingerprint(hashes.SHA1()).hex()
        private_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode("ascii")
        public_pem = cert.public_bytes(Encoding.PEM).decode("ascii")
        return {"private_key": private_pem, "thumbprint": thumb_hex, "public_certificate": public_pem}
    except Exception as e:
        raise RuntimeError(f"PFX load failed: {e}") from e


def transform_graph_messages(items: Sequence[dict], clouds: set[str], since: str | None, months: str | None) -> list[Row]:
    rows: list[Row] = []
    for m in items:
        title = str(m.get("title") or "").strip()
        msg_id = str(m.get("id") or "").strip()
        # Try dates (prefer lastModifiedDateTime)
        lm = m.get("lastModifiedDateTime") or m.get("lastModified") or m.get("publishedDateTime") or ""
        lm_iso = ""
        d = parse_date_soft(str(lm) if lm else None)
        if d:
            lm_iso = d.date().isoformat()

        # Derive public roadmap id from [123456] in title or any 5-7 digit num as fallback
        pub_id = ""
        m1 = RE_ROADMAP_ID.search(title)
        if m1:
            pub_id = m1.group(1)
        else:
            m2 = RE_ANY_ID.search(title or "")
            if m2:
                pub_id = m2.group(1)

        # Services → Product_Workload
        services = m.get("services") or []
        if isinstance(services, str):
            product = services
        else:
            product = ", ".join([str(s) for s in services if str(s).strip()])

        # Status (often absent in MC API; keep blank if unknown)
        status = str(m.get("status") or "").strip()

        # Cloud: Message center is tenant-scoped. If filtering by General, mark General; else blank.
        cloud = "General" if (not clouds or "General" in clouds) else ""

        # Official roadmap link if we found an ID
        link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pub_id}" if pub_id else ""

        row = Row(
            PublicId=pub_id,
            Title=title or f"[{pub_id}]" if pub_id else title,
            Source="graph",
            Product_Workload=product,
            Status=status,
            LastModified=lm_iso,
            ReleaseDate="",  # not present in this API; keep blank
            Cloud_instance=cloud,
            Official_Roadmap_link=link,
            MessageId=msg_id,
        )
        if within_window(row.LastModified, since, months) and include_by_cloud(row, clouds):
            rows.append(row)
    return rows


def _try_fetch_graph(cfg: dict, clouds: set[str], since: str | None, months: str | None) -> tuple[list[Row], str | None]:
    """
    Attempt Graph fetch using certificate creds from cfg.
    On any error, return ([], <error message>).
    """
    try:
        tenant = cfg.get("TENANT") or cfg.get("tenant_id") or cfg.get("tenant")
        client_id = cfg.get("CLIENT") or cfg.get("client_id") or cfg.get("client")
        pfx_b64 = cfg.get("PFX_B64") or cfg.get("pfx_base64") or os.environ.get("M365_PFX_BASE64")

        # The workflow often writes a literal env var key into cfg (e.g. "M365_PFX_PASSWORD")
        pwd_env_key = cfg.get("M365_PFX_PASSWORD") or "M365_PFX_PASSWORD"
        pfx_password = os.environ.get(pwd_env_key)

        if not tenant or not client_id or not pfx_b64:
            return [], "Graph client not available on this runner"

        client_cred = _load_msal_client_credential_from_pfx_b64(pfx_b64, pfx_password)

        authority_base = cfg.get("authority") or cfg.get("authority_base") or "https://login.microsoftonline.com"
        authority = f"{authority_base.rstrip('/')}/{tenant}"
        graph_base = (cfg.get("graph_base") or "https://graph.microsoft.com").rstrip("/")

        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            authority=authority,
            client_credential=client_cred,
        )

        token = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in token:
            short = token.get("error_description") or token.get("error") or "token acquisition failed"
            return [], f"PFX/token error: {short}"

        headers = {"Authorization": f"Bearer {token['access_token']}"}
        url = f"{graph_base}/v1.0/admin/serviceAnnouncement/messages?$top=200"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return [], f"Graph HTTP {resp.status_code}: {resp.text}"

        payload = resp.json()
        items = payload.get("value", [])
        rows = transform_graph_messages(items, clouds=clouds, since=since, months=months)
        return rows, None

    except Exception as e:
        return [], f"graph-fetch failed: {e}"


# -----------------------------
# Fallbacks + seed
# -----------------------------

def _seed_rows_from_ids(seed_ids: str) -> list[Row]:
    rows: list[Row] = []
    for sid in _split_csv_like(seed_ids):
        sid = sid.strip()
        if not sid:
            continue
        link = f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={sid}"
        rows.append(
            Row(
                PublicId=sid,
                Title=f"[{sid}]",
                Source="seed",
                Product_Workload="",
                Status="",
                LastModified="",
                ReleaseDate="",
                Cloud_instance="",
                Official_Roadmap_link=link,
                MessageId="",
            )
        )
    return rows


# -----------------------------
# I/O helpers
# -----------------------------

def write_csv(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELD_ORDER)
        for r in rows:
            d = asdict(r)
            w.writerow([d.get(k, "") for k in FIELD_ORDER])


def write_json(path: str | Path, rows: list[Row]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = []
    for r in rows:
        d = asdict(r)
        data.append({k: d.get(k, "") for k in FIELD_ORDER})
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_stats(path: str | Path, stats: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)


def read_config(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# -----------------------------
# CLI
# -----------------------------

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="Path to graph_config.json", default=None)
    ap.add_argument("--since", help="Include items on/after YYYY-MM-DD", default=None)
    ap.add_argument("--months", help="Include items within last N months", default=None)
    ap.add_argument("--cloud", action="append", default=[], help="Cloud label (repeatable). E.g., 'Worldwide (Standard Multi-Tenant)', 'GCC', 'GCC High', 'DoD'")
    ap.add_argument("--no-graph", action="store_true", help="Skip Graph and use fallbacks/seed only")
    ap.add_argument("--seed-ids", default="", help="Comma/pipe-separated list of exact roadmap IDs to include as seed")
    ap.add_argument("--emit", required=True, choices=["csv", "json"], help="Output format")
    ap.add_argument("--out", required=True, help="Path to write output file")
    ap.add_argument("--stats-out", default=None, help="Optional path to write fetch stats JSON")
    return ap.parse_args(argv)


# -----------------------------
# MAIN
# -----------------------------

def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    cfg = read_config(args.config)

    # Compute selected clouds (canonical set)
    selected: set[str] = set()
    if args.cloud:
        selected |= normalize_clouds(args.cloud)
    # If none specified, default to General to match the GH workflow behavior
    if not selected:
        selected.add("General")

    print(
        f"Running fetch_messages_graph.py with: "
        f"{'--config ' + args.config if args.config else ''} "
        f"{''.join('')} "
        f"--cloud {', '.join(sorted(selected))} "
        f"{'--no-graph' if args.no_graph else ''}"
    )

    all_rows: list[Row] = []
    errors: list[str] = []
    stats = {
        "sources": {"graph": 0, "public-json": 0, "rss": 0, "seed": 0},
        "errors": 0,
    }

    # Graph branch
    if not args.no_graph:
        g_rows, graph_err = _try_fetch_graph(cfg, selected, args.since, args.months)
        if graph_err:
            print(f"WARN: {graph_err}")
            errors.append(graph_err)
        else:
            # keep only after window/cloud filters (already applied by transformer)
            pass
        stats["sources"]["graph"] = len(g_rows)
        all_rows.extend(g_rows)
    else:
        print("INFO: --no-graph set → skipping Graph fetch")

    # (Public JSON / RSS fallbacks would go here if you wire them)
    # Seed IDs
    if args.seed_ids:
        seed_rows = _seed_rows_from_ids(args.seed_ids)
        stats["sources"]["seed"] = len(seed_rows)
        all_rows.extend(seed_rows)

    # De-dup by (Source, MessageId, PublicId, Title) in that preference order
    seen: set[tuple] = set()
    deduped: list[Row] = []
    for r in all_rows:
        key = (r.Source or "", r.MessageId or "", r.PublicId or "", r.Title or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # Final filter by cloud (defensive; already applied in transformer)
    deduped = [r for r in deduped if include_by_cloud(r, selected)]

    # Sort: LastModified desc, then Title
    def _sort_key(r: Row):
        dt = parse_date_soft(r.LastModified) or datetime.min.replace(tzinfo=timezone.utc)
        return (-int(dt.timestamp()), r.Title or "")

    deduped.sort(key=_sort_key)

    # Emit
    out_path = args.out
    if args.emit == "csv":
        write_csv(out_path, deduped)
    else:
        write_json(out_path, deduped)

    # Stats file
    if args.stats_out:
        stats["errors"] = len(errors)
        write_stats(args.stats_out, stats)

    print(
        f"Done. rows={len(deduped)} sources="
        f"{json.dumps(stats['sources'])} errors={len(errors)}"
    )
    # Debug: list output dir
    try:
        out_dir = str(Path(out_path).parent)
        files = sorted(os.listdir(out_dir))
        print(f"DEBUG: files in {out_dir}: {files}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
