#!/usr/bin/env python3
"""
fallback_public_roadmap.py — dynamic scrape for Microsoft 365 Roadmap items by ID.
Renders https://www.microsoft.com/en-us/microsoft-365/roadmap?id=<ID> with Playwright.

Outputs rows in your master schema:
| ID | Title | Product/Workload | Status | Release phase | Targeted dates | Cloud instance | Short description | Official Roadmap link |
"""
from typing import List
from playwright.sync_api import sync_playwright

HEADERS = [
    "ID","Title","Product/Workload","Status","Release phase",
    "Targeted dates","Cloud instance","Short description","Official Roadmap link"
]

def _safe(s: str | None) -> str:
    if not s: return ""
    return " ".join(s.replace("\u200b","").replace("|"," / ").split())

def _extract_field(lines: list[str], label: str) -> str:
    # tolerant extraction: find the label, then gather the next non-empty line(s)
    label_lower = label.lower()
    for i, ln in enumerate(lines):
        if ln.strip().lower().rstrip(":") == label_lower:
            # collect next lines until the next likely label or blank
            val = []
            for j in range(i+1, min(i+6, len(lines))):
                nxt = lines[j].strip()
                if not nxt: break
                # stop when it looks like another label
                if nxt.endswith(":") or len(nxt.split()) <= 3 and nxt.istitle():
                    break
                val.append(nxt)
            return _safe(" ".join(val)) if val else ""
    return ""

def fetch_ids_public(ids: List[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    url_tpl = "https://www.microsoft.com/en-us/microsoft-365/roadmap?id={}"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        for iid in ids:
            iid = iid.strip()
            url = url_tpl.format(iid)
            page.goto(url, wait_until="networkidle", timeout=60000)
            # visible text
            body_text = page.inner_text("body")
            lines = [ln for ln in (body_text or "").splitlines() if ln.strip()]

            # Title from first h1/h2, fallback to lines
            try:
                title = page.locator("h1, h2").first.inner_text(timeout=3000)
            except Exception:
                title = ""
            title = _safe(title) or _extract_field(lines, "Title")

            product = _extract_field(lines, "Product/Workload") or _extract_field(lines, "Product")
            status  = _extract_field(lines, "Status")
            phase   = _extract_field(lines, "Release phase")
            target  = _extract_field(lines, "Targeted dates") or _extract_field(lines, "GA")
            clouds  = _extract_field(lines, "Cloud instance")
            desc    = _extract_field(lines, "Description") or _extract_field(lines, "Summary") or _extract_field(lines, "Overview")

            row = [
                _safe(iid), _safe(title), _safe(product), _safe(status),
                _safe(phase), _safe(target), _safe(clouds), _safe(desc), url
            ]
            rows.append(row)
        ctx.close()
        browser.close()
    return rows
