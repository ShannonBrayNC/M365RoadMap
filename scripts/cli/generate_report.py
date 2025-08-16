#!/usr/bin/env python3
"""
generate_report.py
------------------
Roadmap → Message Center → Web (optional) joiner.

Outputs:
 - output/enriched.json
 - output/roadmap_report.html (simple static HTML for GitHub Pages)

Usage:
  python -m scripts.cli.generate_report --mode auto
    modes: auto | graphOnly | free
Env:
  TENANT_ID, CLIENT_ID, CLIENT_SECRET (for Graph client credentials)
  BING_SEARCH_KEY, BING_SEARCH_ENDPOINT (optional; web enrichment disabled by default)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from typing import  Dict, List, Optional, Tuple

# Third‑party
import requests
from bs4 import BeautifulSoup

# -----------------------------
# Helpers
# -----------------------------

def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _jaccard_title(a: str, b: str) -> float:
    A = set(_norm(a).lower().split())
    B = set(_norm(b).lower().split())
    if not A and not B:
        return 0.0
    return len(A & B) / max(1, len(A | B))

def ensure_outdir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def mc_deeplink(mc_id: str) -> str:
    return f"https://admin.cloud.microsoft.com/#/MessageCenter/:/messages/{mc_id}"

def safe_get(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

# -----------------------------
# Models
# -----------------------------

@dataclass
class SourceLink:
    label: str
    url: str

@dataclass
class EnrichedItem:
    id: str
    title: str
    product: str = ""
    services: List[str] = field(default_factory=list)
    status: Optional[str] = None
    category: Optional[str] = None
    isMajor: Optional[bool] = None
    severity: Optional[str] = None
    lastUpdated: Optional[str] = None
    plannedStart: Optional[str] = None
    plannedEnd: Optional[str] = None
    summary: Optional[str] = None
    confidence: int = 0
    links: List[SourceLink] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["links"] = [asdict(link) for link in self.links]
        return d

# -----------------------------
# Providers
# -----------------------------

def fetch_roadmap(seed_url: str = "https://www.microsoft.com/en-us/microsoft-365/roadmap") -> List[Dict[str, Any]]:
    """
    Best‑effort scrape of Roadmap cards. If empty (site is JS-rendered), we return [] and caller can fallback.
    """
    try:
        r = requests.get(seed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        print(f"[roadmap] fetch error: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []

    # Defensive selectors; MS markup changes from time to time.
    # We iterate over elements that look like a card/root and then query within.
    candidates = soup.select(".roadmap-card, li.roadmap-card, div[data-automation-id='roadmap-card']")
    if not candidates:
        # Fallback: try any container with a card-title
        candidates = [el.parent for el in soup.select("[data-automation-id='card-title']")]

    for el in candidates:
        try:
            # NOTE: No backslash-escaped quotes — plain CSS selectors to avoid Python string escapes issues.
            title_el = el.select_one("[data-automation-id='card-title'], h3, .title")
            product_el = el.select_one("[data-automation-id='card-product'], .product")
            category_el = el.select_one("[data-automation-id='card-category'], .category")
            status_el = el.select_one("[data-automation-id='card-status'], .status")
            summary_el = el.select_one("[data-automation-id='card-summary'], p")

            title = _norm(title_el.get_text(strip=True) if title_el else "")
            product = _norm(product_el.get_text(strip=True) if product_el else "")
            category = _norm(category_el.get_text(strip=True) if category_el else "")
            status = _norm(status_el.get_text(strip=True) if status_el else "")
            summary = _norm(summary_el.get_text(strip=True) if summary_el else "")
            href = el.select_one("a").get("href") if el.select_one("a") else ""
            url = href if href.startswith("http") else f"https://www.microsoft.com{href}" if href else ""

            # Attempt to detect numeric Roadmap ID anywhere in the card
            text = el.get_text(" ", strip=True)
            m = re.search(r"(?:Feature\s*ID|Roadmap\s*ID)\s*[:#]?\s*(\d{5,7})", text, flags=re.I)
            rid = m.group(1) if m else None

            services = []
            if product:
                services.append(product)

            if title and url:
                items.append({
                    "id": rid,
                    "title": title,
                    "product": product,
                    "category": category or None,
                    "status": status or None,
                    "url": url,
                    "services": services,
                    "summary": summary or None
                })
        except Exception:
            # Skip card if anything unexpected
            continue

    return items

def _token_client_credentials(tenant_id: str, client_id: str, client_secret: str) -> Optional[str]:
    try:
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        r = requests.post(token_url, data=data, timeout=20)
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        print(f"[graph] token error: {e}", file=sys.stderr)
        return None

def fetch_message_center() -> List[Dict[str, Any]]:
    tenant = os.getenv("TENANT_ID", "")
    client_id = os.getenv("CLIENT_ID", "")
    client_secret = os.getenv("CLIENT_SECRET", "")
    if not (tenant and client_id and client_secret):
        print("[graph] missing TENANT_ID/CLIENT_ID/CLIENT_SECRET — MC disabled", file=sys.stderr)
        return []

    token = _token_client_credentials(tenant, client_id, client_secret)
    if not token:
        return []

    url = "https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/messages?$top=200"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[graph] fetch error: {e}", file=sys.stderr)
        return []

    rows = []
    for m in data.get("value", []):
        rows.append({
            "id": m.get("id"),
            "title": m.get("title") or "",
            "description": safe_get(m, "body", "content") or m.get("description") or "",
            "services": m.get("services") or [],
            "classification": m.get("classification"),
            "severity": m.get("severity"),
            "isMajorChange": m.get("isMajorChange"),
            "lastModifiedDateTime": m.get("lastModifiedDateTime"),
            "startDateTime": m.get("startDateTime"),
            "endDateTime": m.get("endDateTime"),
        })
    return rows

def fetch_release_comms_rss() -> List[Dict[str, Any]]:
    # Lightweight RSS parser to avoid extra dependency; parse the simple XML manually
    import xml.etree.ElementTree as ET
    url = "https://www.microsoft.com/releasecommunications/api/v2/m365/rss"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"[rss] fetch error: {e}", file=sys.stderr)
        return []

    n#s = {"atom": "http://www.w3.org/2005/Atom", "rss": "http://purl.org/rss/1.0/"}
    items: List[Dict[str, Any]] = []
    # Try generic RSS 2.0
    for it in root.findall(".//item"):
        title = _norm((it.findtext("title") or ""))
        link = _norm((it.findtext("link") or ""))
        guid = _norm((it.findtext("guid") or ""))
        desc = _norm((it.findtext("description") or ""))
        if title and link:
            items.append({"id": guid or None, "title": title, "url": link, "snippet": desc or None})
    return items

# -----------------------------
# Merger
# -----------------------------

def _extract_rm_ids(text: str) -> List[str]:
    ids = set()
    for m in re.finditer(r"(?:RM)?(\d{5,7})", text or "", flags=re.I):
        ids.add(m.group(1))
    return list(ids)

def merge_items(roadmap: List[Dict[str, Any]], mc: List[Dict[str, Any]]) -> List[EnrichedItem]:
    # Pre-index MC by explicit roadmap ID mention
    index_by_rm: Dict[str, List[Dict[str, Any]]] = {}
    for m in mc:
        found = _extract_rm_ids(f"{m.get('title','')} {m.get('description','')}")
        for rid in found:
            index_by_rm.setdefault(rid, []).append(m)

    out: List[EnrichedItem] = []

    for r in roadmap:
        candidates: List[Tuple[Dict[str, Any], int]] = []

        rid = r.get("id")
        if rid and rid in index_by_rm:
            for m in index_by_rm[rid]:
                candidates.append((m, 70))

        for m in mc:
            ts = _jaccard_title(r.get("title",""), m.get("title",""))
            score = int(round(ts * 50))
            r_svcs = [s.lower() for s in r.get("services", [])]
            m_svcs = [s.lower() for s in m.get("services", [])]
            if any(s in m_svcs for s in r_svcs if s):
                score += 15
            if m.get("startDateTime") or m.get("lastModifiedDateTime"):
                score += 5
            if score >= 35:
                candidates.append((m, score))

        best = None
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            best = candidates[0]

        links = [SourceLink("Roadmap", r.get("url",""))]
        severity = None
        isMajor = None
        lastUpdated = None

        if best:
            m, sc = best
            links.append(SourceLink("Message Center", mc_deeplink(m["id"])))
            severity = m.get("severity")
            isMajor = m.get("isMajorChange")
            lastUpdated = m.get("lastModifiedDateTime")
            confidence = sc
        else:
            confidence = 0

        out.append(EnrichedItem(
            id = rid or (f"MC:{best[0]['id']}" if best else f"RM:{_norm(r.get('title',''))[:20]}"),
            title = r.get("title",""),
            product = r.get("product",""),
            services = r.get("services",[]) or [],
            status = r.get("status"),
            category = r.get("category"),
            isMajor = isMajor,
            severity = severity,
            lastUpdated = lastUpdated,
            summary = r.get("summary"),
            confidence = confidence,
            links = links,
            sources = {
                "roadmap": {"id": rid, "url": r.get("url","")},
                "messageCenter": {"id": best[0]["id"], "url": mc_deeplink(best[0]["id"])} if best else None,
            }
        ))

    # Include MC-only items
    for m in mc:
        exists = any(it.sources.get("messageCenter",{}).get("id") == m["id"] for it in out if it.sources.get("messageCenter"))
        if exists:
            continue
        out.append(EnrichedItem(
            id = f"MC:{m['id']}",
            title = m.get("title",""),
            product = (m.get("services") or [""])[0],
            services = m.get("services") or [],
            isMajor = m.get("isMajorChange"),
            severity = m.get("severity"),
            lastUpdated = m.get("lastModifiedDateTime"),
            confidence = 100,
            links = [SourceLink("Message Center", mc_deeplink(m["id"]))],
            sources = {"messageCenter": {"id": m["id"], "url": mc_deeplink(m["id"])}}
        ))

    return out

# -----------------------------
# HTML Report
# -----------------------------

def write_simple_html(items: List[EnrichedItem], path: str) -> None:
    rows = []
    for it in items:
        chips = " ".join(
                f'<a class="chip" href="{link.url}" target="_blank" rel="noreferrer">{link.label}</a>'
                for link in it.links if link.url
            )
        rows.append(f"""
<tr>
  <td>{it.id}</td>    
  <td>{it.title}</td>
  <td>{it.product}</td>
  <td>{", ".join(it.services)}</td>
  <td>{it.status or ""}</td>
  <td>{it.severity or ""}</td>
  <td>{it.lastUpdated or ""}</td>
  <td>{chips}</td>
</tr>
""")
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>M365 Roadmap Report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; padding: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; position: sticky; top: 0; }}
    .chip {{ display:inline-block; padding: 2px 8px; border:1px solid #d1d5db; border-radius:9999px; font-size:12px; margin-right:6px; }}
  </style>
</head>
<body>
  <h1>M365 Roadmap Report</h1>
  <p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Title</th><th>Product</th><th>Services</th>
        <th>Status</th><th>MC Severity</th><th>Updated</th><th>Links</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>"""
    ensure_outdir(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

# -----------------------------
# Fallback seeds
# -----------------------------

def load_seed_items() -> List[Dict[str, Any]]:
    # Try typical local seeds used during dev/CI
    candidates = [
        "output/roadmap_report_master.json",
        "data/M365RoadMap_Test.json",
        "M365RoadMap_Test.json",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Accept either array of objects with title/product or the enriched schema
                if isinstance(data, list):
                    return data
                # or possibly {"items": [...]}
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    return data["items"]
            except Exception as e:
                print(f"[seed] failed to read {p}: {e}", file=sys.stderr)
    return []

# -----------------------------
# Main
# -----------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto","graphOnly","free"], default="auto", help="Source mode")
    ap.add_argument("--outdir", default="output", help="Output directory")
    ap.add_argument("--web", action="store_true", help="(reserved) include web enrichment (disabled in this script)")
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    out_json = os.path.join(args.outdir, "enriched.json")
    out_html = os.path.join(args.outdir, "roadmap_report.html")

    # 1) Roadmap is the guide
    roadmap = fetch_roadmap()
    if not roadmap:
        # JS-rendered page or network block — try local seeds
        seed = load_seed_items()
        # Normalize seed if it's already enriched structure
        normalized = []
        for it in seed:
            if "title" in it and "url" in it:
                # likely a roadmap-like raw item
                normalized.append({
                    "id": it.get("id"),
                    "title": it.get("title"),
                    "product": it.get("product",""),
                    "category": it.get("category"),
                    "status": it.get("status"),
                    "url": it.get("url"),
                    "services": it.get("services") or ([it.get("product")] if it.get("product") else []),
                    "summary": it.get("summary"),
                })
            elif "sources" in it and it["sources"].get("roadmap"):
                # already enriched — extract roadmap face
                rsrc = it["sources"]["roadmap"]
                normalized.append({
                    "id": rsrc.get("id"),
                    "title": it.get("title",""),
                    "product": it.get("product",""),
                    "category": it.get("category"),
                    "status": it.get("status"),
                    "url": rsrc.get("url",""),
                    "services": it.get("services") or [],
                    "summary": it.get("summary"),
                })
        roadmap = normalized

    # 2) Message Center (Graph) unless mode == free
    mc: List[Dict[str, Any]] = []
    if args.mode in ("auto", "graphOnly"):
        mc = fetch_message_center()
        if args.mode == "graphOnly" and not mc:
            print("[graphOnly] Graph failed or returned empty. Exiting with error.", file=sys.stderr)
            return 2

    # 3) Merge
    items = merge_items(roadmap, mc)

    # 4) Write outputs
    ensure_outdir(out_json)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([it.to_dict() for it in items], f, indent=2, ensure_ascii=False)
    print(f"[ok] wrote {out_json} ({len(items)} items)")

    write_simple_html(items, out_html)
    print(f"[ok] wrote {out_html}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
