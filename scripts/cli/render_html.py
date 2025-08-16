#!/usr/bin/env python3
"""
render_html.py
Reads output/enriched.json and generates a static, styled index (output/roadmap_report.html)
plus per-item detail pages (output/pages/<id>.html).

Usage:
  python render_html.py [--in output/enriched.json] [--out output/roadmap_report.html] [--details output/pages]

Schema (best‑effort, fields are optional):
  id, title, product, services[], status, category, isMajor, severity, lastUpdated, summary, confidence,
  links[{label,url}], sources{ roadmap{url,id}, messageCenter{url,id}, web[...] }
"""
from __future__ import annotations
import os
import json
import html
import re
import argparse
import datetime
from pathlib import Path

def slugify(s: str) -> str:
    s = re.sub(r'[^a-zA-Z0-9\-_]+', '-', s.strip())
    s = re.sub(r'-{2,}', '-', s).strip('-').lower()
    return s or "item"

def norm(s: str|None) -> str:
    return (s or "").strip()

def read_json(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSON not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f"Invalid JSON in {path}: {e}")
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        raise SystemExit("Expected a list of items in the JSON")
    return data

def html_escape(s: str|None) -> str:
    return html.escape(s or "")

CSS = r"""
:root{
  --bg:#0b0f17; --card:#121826; --muted:#9aa4b2; --text:#e6edf3; --acc:#60a5fa; --chip:#1f2937; --chip-b:#334155;
  --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; --line:#233043; --shadow:0 10px 24px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial,sans-serif;background:var(--bg);color:var(--text)}
a{color:var(--acc);text-decoration:none} a:hover{text-decoration:underline}
.container{max-width:1200px;margin:0 auto;padding:24px}
.header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px}
.title{font-size:22px;font-weight:800;letter-spacing:.2px}
.controls{display:flex;gap:10px;flex-wrap:wrap;margin-left:auto}
.input, .select{background:var(--card);border:1px solid var(--line);color:var(--text);padding:10px 12px;border-radius:12px;outline:none;min-width:220px}
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;background:var(--chip);border:1px solid var(--chip-b);font-size:12px;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media (max-width:1100px){.grid{grid-template-columns:repeat(2,1fr)}}
@media (max-width:720px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:var(--shadow);transition:transform .15s ease, border-color .15s ease, box-shadow .15s}
.card:hover{transform:translateY(-2px);border-color:#3b82f6;box-shadow:0 14px 30px rgba(0,0,0,.45)}
.card h3{margin:0 0 8px 0;font-size:16px}
.kv{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}
.kv .kvp{font-size:12px;color:var(--muted)}
.links{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.chip{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:var(--chip);border:1px solid var(--chip-b);font-size:12px}
.chip .dot{width:8px;height:8px;border-radius:999px;background:var(--muted)}
.chip.ok .dot{background:var(--ok)} .chip.warn .dot{background:var(--warn)} .chip.bad .dot{background:var(--bad)}
.small{font-size:12px;color:var(--muted)}
.footer{margin-top:30px;color:var(--muted);font-size:12px;text-align:center}
.sep{height:1px;background:var(--line);margin:14px 0}
/* detail page */
.detail h1{font-size:26px;margin:0 0 12px 0}
.section{margin-top:14px}
.section h2{font-size:14px;margin:0 0 8px 0;color:#c7d2fe}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:var(--shadow)}
.kv-table{display:grid;grid-template-columns:160px 1fr;gap:6px;font-size:13px}
.kv-table .k{color:var(--muted)} .kv-table .v{color:var(--text)}
.btn{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--text)}
.btn:hover{border-color:#3b82f6}
.empty{padding:24px;border:1px dashed var(--line);border-radius:12px;color:var(--muted);text-align:center}
"""

JS = r"""
(function(){
  const q = document.getElementById('q');
  const selProduct = document.getElementById('f-product');
  const selStatus = document.getElementById('f-status');
  const selSeverity = document.getElementById('f-sev');

  function norm(s){ return (s||'').toLowerCase(); }

  function apply(){
    const term = norm(q.value);
    const fp = norm(selProduct.value);
    const fs = norm(selStatus.value);
    const fv = norm(selSeverity.value);
    document.querySelectorAll('.card').forEach((card)=>{
      const text = norm(card.getAttribute('data-text'));
      const product = norm(card.getAttribute('data-product'));
      const status = norm(card.getAttribute('data-status'));
      const sev = norm(card.getAttribute('data-severity'));
      let show = true;
      if (term && !text.includes(term)) show = false;
      if (fp && product !== fp) show = false;
      if (fs && status !== fs) show = false;
      if (fv && sev !== fv) show = false;
      card.style.display = show ? '' : 'none';
    });
    // counts
    const visible = Array.from(document.querySelectorAll('.card')).filter(c => c.style.display !== 'none').length;
    const total = document.querySelectorAll('.card').length;
    const badge = document.getElementById('count');
    if (badge) badge.textContent = visible + ' / ' + total;
    document.getElementById('empty')?.classList.toggle('hidden', visible !== 0);
  }
  ['input','change'].forEach(ev => {
    q.addEventListener(ev, apply);
    selProduct.addEventListener(ev, apply);
    selStatus.addEventListener(ev, apply);
    selSeverity.addEventListener(ev, apply);
  });
  apply();
})(); 
"""

def build_index(items: list[dict], out_html: Path, details_dir: Path):
    # Collect filters
    products = sorted({ norm(x.get("product") or (x.get("services") or [""])[0]) for x in items if norm(x.get("product") or (x.get("services") or [""])[0]) })
    statuses = sorted({ norm(x.get("status")) for x in items if norm(x.get("status")) })
    severities = sorted({ norm(x.get("severity")) for x in items if norm(x.get("severity")) })

    def sel_options(values: list[str]) -> str:
        opts = ['<option value=""></option>'] + [f'<option value="{html_escape(v)}">{html_escape(v)}</option>' for v in values if v]
        return "\n".join(opts)

    cards_html = []
    for it in items:
        it_id = norm(it.get("id")) or slugify(it.get("title",""))[:24]
        title = html_escape(it.get("title"))
        product = norm(it.get("product") or (it.get("services") or [""])[0])
        status = norm(it.get("status"))
        sev = norm(it.get("severity"))
        last = norm(it.get("lastUpdated"))
        summary = it.get("summary") or ""
        summary_short = (summary or "")[:160] + ("…" if summary and len(summary)>160 else "")
        links = it.get("links") or []
        services = it.get("services") or []
        conf = it.get("confidence") or 0

        chips = "".join(f'<a class="chip" href="{html_escape(l.get("url"))}" target="_blank" rel="noreferrer">{html_escape(l.get("label") or "Link")}</a>' for l in links)
        sev_class = "ok" if sev in ("low","informational","normal") else ("warn" if sev in ("medium","elevated") else ("bad" if sev in ("high","critical") else ""))
        services_txt = ", ".join(services)

        data_text = html_escape(" ".join([it.get("title") or "", product, services_txt, summary]))
        detail_href = f"{details_dir.name}/{it_id}.html"

        cards_html.append(f"""
<article class="card" data-text="{data_text}" data-product="{html_escape(product.lower())}" data-status="{html_escape(status.lower())}" data-severity="{html_escape(sev.lower())}">
  <h3><a href="{detail_href}">{title}</a></h3>
  <div class="kv">
    <span class="kvp">ID: {html_escape(it.get("id") or "—")}</span>
    <span class="kvp">Product: {html_escape(product or "—")}</span>
    <span class="kvp">Status: {html_escape(status or "—")}</span>
    <span class="kvp chip {sev_class}"><span class="dot"></span>Severity: {html_escape(sev or "—")}</span>
    <span class="kvp">Updated: {html_escape(last or "—")}</span>
    <span class="kvp">Match: {int(conf)}%</span>
  </div>
  <div class="small">{html_escape(summary_short)}</div>
  <div class="links">{chips}</div>
</article>
""")

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    body = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>M365 Roadmap (Enriched)</title>
<style>{CSS}</style>
<body>
  <div class="container">
    <div class="header">
      <div class="title">M365 Roadmap (Enriched)</div>
      <div class="badge" title="visible / total"><span id="count">0 / 0</span></div>
      <div class="controls">
        <input id="q" class="input" type="search" placeholder="Search title / product / services..." />
        <select id="f-product" class="select" title="Product filter">{sel_options(products)}</select>
        <select id="f-status" class="select" title="Status filter">{sel_options(statuses)}</select>
        <select id="f-sev" class="select" title="Severity filter">{sel_options(severities)}</select>
      </div>
    </div>
    <div class="sep"></div>
    {"<div id='empty' class='empty'>No items. Did you generate <code>output/enriched.json</code>?</div>" if not cards_html else ""}
    <section class="grid">
      {"".join(cards_html)}
    </section>
    <div class="footer">Generated {now} · Static HTML (no JS deps)</div>
  </div>
<script>{JS}</script>
</body>
</html>"""
    out_html.write_text(body, encoding="utf-8")

def build_detail(item: dict, out_file: Path, root_rel: str):
    it_id = norm(item.get("id")) or slugify(item.get("title",""))[:24]
    title = item.get("title") or "Untitled"
    product = norm(item.get("product") or (item.get("services") or [""])[0])
    status = norm(item.get("status"))
    sev = norm(item.get("severity"))
    last = norm(item.get("lastUpdated"))
    summary = item.get("summary") or "*summary pending*"
    services = item.get("services") or []
    links = item.get("links") or []
    chips = "".join(f'<a class="chip" href="{html_escape(ll.get("url"))}" target="_blank" rel="noreferrer">{html_escape(ll.get("label") or "Link")}</a>' for ll in links)

    sev_class = "ok" if sev in ("low","informational","normal") else ("warn" if sev in ("medium","elevated") else ("bad" if sev in ("high","critical") else ""))

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    body = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{html_escape(title)}</title>
<style>{CSS}</style>
<body>
  <div class="container detail">
    <a class="btn" href="{root_rel}">&larr; Back to all</a>
    <h1>{html_escape(title)}</h1>
    <div class="panel">
      <div class="kv-table">
        <div class="k">Roadmap ID</div><div class="v">{html_escape(item.get("id") or "—")}</div>
        <div class="k">Product / Workload</div><div class="v">{html_escape(product or "—")}</div>
        <div class="k">Services</div><div class="v">{html_escape(", ".join(services) or "—")}</div>
        <div class="k">Status</div><div class="v">{html_escape(status or "—")}</div>
        <div class="k">Severity</div><div class="v"><span class="chip {sev_class}"><span class="dot"></span>{html_escape(sev or "—")}</span></div>
        <div class="k">Last Modified</div><div class="v">{html_escape(last or "—")}</div>
      </div>
      <div class="links" style="margin-top:10px">{chips}</div>
    </div>

    <div class="section">
      <h2>Summary</h2>
      <div class="panel">{html_escape(summary)}</div>
    </div>

    <div class="section">
      <h2>What's changing</h2>
      <div class="panel small">*pending — add from Message Center text or your summaries*</div>
    </div>

    <div class="section">
      <h2>Impact and rollout</h2>
      <div class="panel small">*pending — add rollout, clouds, channels*</div>
    </div>

    <div class="section">
      <h2>Action items</h2>
      <div class="panel small">*pending — admin tasks/controls*</div>
    </div>

    <div class="footer">Generated {now}</div>
  </div>
</body>
</html>"""
    out_file.write_text(body, encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="output/enriched.json")
    ap.add_argument("--out", dest="out", default="output/roadmap_report.html")
    ap.add_argument("--details", dest="details", default="output/pages")
    args = ap.parse_args()

    inp = Path(args.inp)
    out = Path(args.out)
    details = Path(args.details)

    items = read_json(inp)
    out.parent.mkdir(parents=True, exist_ok=True)
    details.mkdir(parents=True, exist_ok=True)

    # Build index
    build_index(items, out, details)

    # Build detail pages
    for it in items:
        it_id = norm(it.get("id")) or slugify(it.get("title",""))[:24]
        out_file = details / f"{it_id}.html"
        root_rel = os.path.relpath(out, out_file.parent).replace('\\','/')
        build_detail(it, out_file, root_rel)

    print(f"✔ Wrote {out} and {len(list(details.glob('*.html')))} detail pages to {details}/")

if __name__ == "__main__":
    main()
