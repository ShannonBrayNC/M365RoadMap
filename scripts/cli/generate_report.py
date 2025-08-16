from __future__ import annotations
import os, json, sys, pathlib, time, argparse, traceback, datetime as dt
from typing import Any, Dict, List, Optional
import requests

# Optional deps handled lazily
try:
    import msal  # type: ignore
except Exception:  # pragma: no cover
    msal = None  # we allow free mode without Graph

try:
    import feedparser  # type: ignore
except Exception:  # pragma: no cover
    feedparser = None

# Local modules
from scripts.enrich.merge_items import merge_items
from scripts.enrich.types import dump_enriched

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTDIR = ROOT / "output"
DATADIR = ROOT / "data"

ROADMAP_FALLBACK_JSON = (OUTDIR / "roadmap_report_master.json", DATADIR / "M365RoadMap_Test.json")

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/messages?$top=50"
RELEASE_COMMS_RSS = "https://www.microsoft.com/releasecommunications/api/v2/m365/rss"

def _load_seed_roadmap() -> List[Dict[str, Any]]:
    for p in ROADMAP_FALLBACK_JSON:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    # minimal seed if nothing exists
    return [{
        "id": None,
        "title": "Sample: Outlook - Suggested replies updates",
        "product": "Outlook",
        "status": "Launched",
        "category": "Feature update",
        "url": "https://www.microsoft.com/en-us/microsoft-365/roadmap?filters=&searchterms=outlook"
    }]

def _ms_graph_messages() -> List[Dict[str, Any]]:
    tenant = os.getenv("TENANT_ID")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    if not (tenant and client_id and client_secret and msal):
        raise RuntimeError("Graph creds missing or msal not installed")
    app = msal.ConfidentialClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=client_secret
    )
    token = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    access = token.get("access_token")
    if not access:
        raise RuntimeError(f"Token failure: {token}")
    headers = {"Authorization": f"Bearer {access}"}
    items: List[Dict[str, Any]] = []
    url = GRAPH_ENDPOINT
    for _ in range(5):  # simple paging guard
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Graph MC fetch failed: {r.status_code} {r.text[:200]}")
        data = r.json()
        items.extend(data.get("value", []))
        nxt = data.get("@odata.nextLink")
        if not nxt: break
        url = nxt
    # normalize a bit
    normd = []
    for m in items:
        normd.append({
            "id": m.get("id"),
            "title": m.get("title"),
            "description": (m.get("body") or {}).get("content") or m.get("description") or "",
            "services": m.get("services") or [],
            "classification": m.get("classification"),
            "severity": m.get("severity"),
            "isMajorChange": m.get("isMajorChange"),
            "lastModifiedDateTime": m.get("lastModifiedDateTime"),
            "startDateTime": m.get("startDateTime"),
            "endDateTime": m.get("endDateTime"),
        })
    return normd

def _release_comms_hits() -> List[Dict[str, Any]]:
    if not feedparser:
        return []
    try:
        feed = feedparser.parse(RELEASE_COMMS_RSS)
        out = []
        for it in (feed.entries or []):
            out.append({
                "title": it.get("title"),
                "url": it.get("link"),
                "snippet": it.get("summary") or it.get("content", [{}])[0].get("value") if it.get("content") else None
            })
        return out
    except Exception:
        return []

def _write_html(enriched: List[Dict[str, Any]], out_html: pathlib.Path) -> None:
    # tiny static HTML view
    rows = ""
    for e in enriched:
        links = " ".join(f'<a href="{l["url"]}" target="_blank">{l["label"]}</a>' for l in e.get("links", []))
        sev = e.get("severity") or ""
        maj = "Yes" if e.get("isMajor") else ""
        rows += f"<tr><td>{e.get('title','')}</td><td>{e.get('product','')}</td><td>{e.get('status','')}</td><td>{sev}</td><td>{maj}</td><td>{links}</td></tr>\n"
    html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>M365 Roadmap Report</title>
<style>body{{font-family:system-ui,Segoe UI,Arial,sans-serif;padding:20px}} table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ddd;padding:8px}} th{{background:#f5f5f5}}</style>
</head><body>
<h1>M365 Roadmap Report</h1>
<p>Generated: {dt.datetime.utcnow().isoformat()}Z</p>
<table>
<thead><tr><th>Title</th><th>Product</th><th>Status</th><th>Severity</th><th>Major</th><th>Links</th></tr></thead>
<tbody>
{rows}
</tbody></table>
</body></html>"""
    out_html.write_text(html, encoding="utf-8")

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate enriched roadmap report")
    ap.add_argument("--mode", choices=["auto","graphOnly","free"], default="auto", help="Data sources mode")
    ap.add_argument("--with-web", action="store_true", help="Attach Release Comms RSS as 'Web' chips (best effort)")
    args = ap.parse_args(argv)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    # Load roadmap seed
    roadmap = _load_seed_roadmap()

    mc_items: List[Dict[str, Any]] = []
    web_hits: List[Dict[str, Any]] = []

    if args.mode in ("auto","graphOnly"):
        try:
            mc_items = _ms_graph_messages()
        except Exception as e:
            if args.mode == "graphOnly":
                print(f"[ERROR] Graph-only mode failed: {e}", file=sys.stderr)
                return 2
            else:
                print(f"[WARN] Graph failed, degrading to free: {e}", file=sys.stderr)

    if args.with_web or not mc_items:
        web_hits = _release_comms_hits()

    enriched_items = merge_items(roadmap, mc_items, web_hits, with_web=bool(web_hits))

    enriched_json_path = OUTDIR / "enriched.json"
    enriched_json_path.write_text(json.dumps([e for e in map(dict, enriched_items,)], indent=2, ensure_ascii=False), encoding="utf-8")

    # also write HTML table view
    _write_html([e for e in map(dict, enriched_items,)], OUTDIR / "roadmap_report.html")

    # write a tiny stats file for CI
    stats = {
        "count": len(enriched_items),
        "graph_used": bool(mc_items),
        "web_hits": len(web_hits),
        "generated_utc": dt.datetime.utcnow().isoformat() + "Z",
        "mode": args.mode,
    }
    (OUTDIR / "fetch_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(f"Wrote: {enriched_json_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
