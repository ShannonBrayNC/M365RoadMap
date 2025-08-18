#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
import html
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List

# Enrichment (prefer the real module if present)
try:
    from scripts.enrich import enrich_item
except Exception:
    # Minimal inline fallback if enrich.py isn't available yet
    from typing import Mapping, Set
    import re

    def _split_cloud_tokens(val: str):
        return [p.strip() for p in re.split(r"[,\|;/]+", val) if p.strip()]

    _CLOUD_SYNONYMS = {
        "worldwide (standard multi-tenant)": "General",
        "worldwide": "General",
        "general": "General",
        "gcc": "GCC",
        "gcc high": "GCC High",
        "gcch": "GCC High",
        "gcc-high": "GCC High",
        "dod": "DoD",
        "government community cloud": "GCC",
    }

    def normalize_clouds(value: Any) -> Set[str]:
        parts = []
        if value is None or value == "":
            parts = []
        elif isinstance(value, str):
            parts = (
                _split_cloud_tokens(value)
                if any(d in value for d in ",|;/")
                else [value.strip()]
            )
        elif isinstance(value, (list, tuple, set)):
            for v in value:
                if v is None:
                    continue
                sv = str(v)
                parts.extend(
                    _split_cloud_tokens(sv)
                    if any(d in sv for d in ",|;/")
                    else [sv.strip()]
                )
        else:
            parts = [str(value).strip()]
        out = set()
        for p in parts or ["General"]:
            out.add(_CLOUD_SYNONYMS.get(p.lower(), p if p else "General"))
        return out

    def extract_clouds(src: Any) -> Set[str]:
        if isinstance(src, dict):
            for k in ("clouds", "cloud", "Clouds", "Cloud"):
                if k in src:
                    return normalize_clouds(src.get(k))
            return {"General"}
        return normalize_clouds(src)

    def _get(it: Mapping[str, Any], keys):
        for k in keys:
            if k in it and it[k]:
                return it[k]
        return ""

    def enrich_item(it: Mapping[str, Any]) -> Dict[str, Any]:
        from datetime import datetime

        def parse_status(m):
            for k in ("status", "Status", "lifecycle", "Lifecycle"):
                if k in m and m[k]:
                    raw = str(m[k]).strip()
                    key = raw.lower()
                    return {
                        "launched": "Launched",
                        "rolling out": "Rolling out",
                        "in development": "In development",
                        "canceled": "Cancelled",
                        "cancelled": "Cancelled",
                    }.get(key, raw)
            return "—"

        def parse_release(m):
            for k in (
                "releaseDate",
                "release",
                "Release",
                "Release Date",
                "release_date",
                "targetRelease",
            ):
                if k in m and m[k]:
                    val = str(m[k])
                    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m"):
                        try:
                            dtx = (
                                datetime.strptime(val[:10], fmt)
                                if len(val) >= len(fmt)
                                else datetime.strptime(val, fmt)
                            )
                            return dtx.strftime("%Y-%m")
                        except Exception:
                            pass
                    return val
            return "—"

        def clean_title(s: str) -> str:
            import re

            return re.sub(r"^\((updated|update)\)\s*", "", s or "", flags=re.I).strip()

        title = clean_title(_get(it, ("title", "Title", "subject")))
        product = str(
            _get(it, ("product", "Product", "workload", "Workload", "category"))
        ).strip()
        change = title.split(":", 1)[1].strip() if ":" in title else title
        if not product and ":" in title:
            left = title.split(":", 1)[0].strip()
            if len(left.split()) <= 6:
                product = left
        change = change.replace("Microsoft ", "").strip()
        note = (
            (f"Update to {product}: {change}." if product else f"Update: {change}.")
            if title
            else "Auto-summary unavailable."
        )
        if len(note) > 220:
            note = note[:217].rstrip() + "…"
        clouds = extract_clouds(it) or {"General"}
        clouds_display = ", ".join(sorted(clouds, key=lambda s: (s != "General", s)))
        out = dict(it)
        out.update(
            {
                "status_display": parse_status(it),
                "release_display": parse_release(it),
                "clouds_display": clouds_display,
                "ai_notes": note,
            }
        )
        return out


def render(
    items: List[Dict[str, Any]],
    title: str,
    cloud_filter: str | None,
    css_href: str,
    js_src: str,
) -> str:
    def esc(s):
        return html.escape(str(s)) if s is not None else ""

    toc_items = []
    cards = []
    for it in items:
        rid = esc(
            it.get("id")
            or it.get("Roadmap ID")
            or it.get("roadmapId")
            or it.get("roadmap_id")
            or it.get("messageId")
            or it.get("Message ID")
            or it.get("id")
        )
        anchor = f"rm-{rid}" if rid else f"rm-{len(cards) + 1}"
        link = (
            it.get("link")
            or it.get("url")
            or it.get("webLink")
            or it.get("Roadmap URL")
            or ""
        )
        h3_text = it.get("title") or it.get("Title") or ""
        toc_items.append(f'<li><a href="#{anchor}">{esc(h3_text)}</a></li>')
        pills_meta = (
            '<div class="rm-meta-pills">'
            f'<span class="rm-pill"><strong>Status:</strong> {esc(it.get("status_display", "—"))}</span>'
            f'<span class="rm-pill"><strong>Release:</strong> {esc(it.get("release_display", "—"))}</span>'
            f'<span class="rm-pill"><strong>Clouds:</strong> {esc(it.get("clouds_display", "—"))}</span>'
            "</div>"
        )
        product_list = (
            it.get("product")
            or it.get("Product")
            or it.get("workload")
            or it.get("Workload")
            or ""
        )
        prod_html = ""
        if product_list:
            prods = [p.strip() for p in str(product_list).split("/") if p.strip()]
            prod_html = (
                '<div class="rm-pills" aria-label="Products">'
                + "".join(f'<span class="rm-pill">{esc(p)}</span>' for p in prods)
                + "</div>"
            )
        table_html = (
            '<div class="table-wrap"><table class="rm-table">'
            "<tbody>"
            f"<tr><th>Roadmap ID</th><td>{esc(rid)}</td><th>Status</th><td>{esc(it.get('status_display', '—'))}</td></tr>"
            f"<tr><th>Product / Workload</th><td>{esc(product_list)}</td><th>Cloud(s)</th><td>{esc(it.get('clouds_display', '—'))}</td></tr>"
            f"<tr><th>Last Modified</th><td>{esc(it.get('lastModified') or it.get('Last Modified') or it.get('last_modified') or '—')}</td><th>Release Date</th><td>{esc(it.get('release_display', '—'))}</td></tr>"
            f"<tr><th>Source</th><td>{esc(it.get('source') or '—')}</td><th>Message ID</th><td>{esc(it.get('messageId') or it.get('Message ID') or '—')}</td></tr>"
            "</tbody></table></div>"
        )
        sources = []
        if link:
            sources.append(f'<a href="{esc(link)}">Official Roadmap</a>')
        if it.get("messageId") or it.get("Message ID"):
            mid = it.get("messageId") or it.get("Message ID")
            sources.append(
                f'<a href="https://admin.microsoft.com/#/MessageCenter/:/messages/{esc(mid)}">{esc(mid)}</a>'
            )
        sources_html = " | ".join(sources) if sources else "—"
        ai_notes = esc(it.get("ai_notes", ""))
        summary_block = (
            '<div class="rm-sect">'
            "<h4>AI notes</h4>"
            f"<div>{ai_notes or '—'}</div>"
            f'<div style="margin-top:6px;font-size:.9rem;color:#555;">Sources: {sources_html}</div>'
            "</div>"
        )
        card = (
            f'<div class="rm-wrap rm-card" id="{anchor}">'
            f'<h3><strong><a href="{esc(link) if link else "#"}">{esc(h3_text)}</a></strong></h3>'
            f"{pills_meta}{prod_html}{table_html}{summary_block}</div>"
        )
        cards.append(card)

    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


header = (
    "<!doctype html>\n"
    "<html>\n"
    "  <head>\n"
    '    <meta charset="utf-8">\n'
    '    <meta name="viewport" content="width=device-width, initial-scale=1">\n'
    f"    <title>{html.escape(title)}</title>\n"
    f'    <link rel="stylesheet" href="{html.escape(css_href)}">\n'
    "  </head>\n"
    "  <body>\n"
    '    <div class="rm-wrap rm-header">\n'
    f"      <h1>{html.escape(title)}</h1>\n"
    '      <div class="rm-meta">\n'
    f"        Generated <strong>{now}</strong> · Cloud filter: <strong>{html.escape(cloud_filter or 'All')}</strong>\n"
    "      </div>\n"
    "    </div>\n"
    f'    <div class="rm-wrap"><div class="rm-meta">Total features: <strong>{len(items)}</strong></div></div>\n'
    '    <div class="rm-wrap rm-toc">\n'
    "      <h3>Contents</h3>\n"
    "      <ol>\n" + "".join(toc_items) + "      </ol>\n"
    "    </div>\n"
) + footer


def main():
    ap = argparse.ArgumentParser(description="Generate Roadmap report HTML")
    ap.add_argument(
        "--input",
        default="M365RoadMap_Test.json",
        help="Input JSON file (list of items)",
    )
    ap.add_argument(
        "--out",
        default="M365RoadMap/output/roadmap_report.html",
        help="Output HTML path",
    )
    ap.add_argument("--title", default="roadmap_report", help="Report title")
    ap.add_argument(
        "--cloud", default=None, help="Cloud filter label to display (cosmetic only)"
    )
    ap.add_argument(
        "--css", default="assets/roadmap.css", help="Href path to CSS in the repo"
    )
    ap.add_argument(
        "--js", default="assets/roadmap.enhance.js", help="Src path to JS in the repo"
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[ERR] Input not found: {in_path}", file=sys.stderr)
        sys.exit(2)
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        print("[ERR] Input JSON must be a list of items (dicts).", file=sys.stderr)
        sys.exit(3)

    enriched = [enrich_item(it) for it in data]
    html_text = render(
        enriched, args.title, args.cloud, css_href=args.css, js_src=args.js
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")
    print(f"[OK] Wrote {out_path} ({len(enriched)} items)")


if __name__ == "__main__":
    main()
