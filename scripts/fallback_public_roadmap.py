#!/usr/bin/env python3
"""
fallback_public_roadmap.py
Scrape public Microsoft 365 Roadmap feature pages with Playwright.

Exported:
    fetch_ids_public(id_list: list[str]) -> list[list[str]]
        Returns rows shaped like TABLE_HEADERS used by the pipeline.

Notes:
- Requires 'playwright' to be installed and the Chromium browser installed.
- The page is dynamic; we wait for network idle and parse text heuristically.
"""

from __future__ import annotations

import re
from typing import List
from playwright.sync_api import sync_playwright

TABLE_HEADERS = [
    "ID","Title","Product/Workload","Status","Release phase",
    "Targeted dates","Cloud instance","Short description","Official Roadmap link"
]

ROADMAP_URL = "https://www.microsoft.com/en-us/microsoft-365/roadmap?featureid={fid}"

def _clean(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.replace("\u200b", "").replace("|"," / ").split())

def _split_title_product(title: str) -> tuple[str, str]:
    """
    Title often looks like 'Microsoft Teams: Chat Notes'.
    Return (product/workload, title_without_product)
    """
    if ":" in title:
        left, right = title.split(":", 1)
        return _clean(left), _clean(right)
    return "", _clean(title)

def _extract_field_by_label(text: str, labels: list[str]) -> str:
    """
    Find 'Label: value' or 'Label value' style in a large text blob.
    Returns first match; else "".
    """
    for label in labels:
        # strict: 'Label: value'
        m = re.search(rf"{re.escape(label)}\s*:\s*(.+?)\s{1,3}([A-Z][a-z]+:|$)", text, flags=re.S)
        if m:
            return _clean(m.group(1)).rstrip(":")
        # looser: 'Label value' up to line break
        m2 = re.search(rf"{re.escape(label)}\s+([^\n\r]+)", text)
        if m2:
            return _clean(m2.group(1))
    return ""

def _guess_fields_from_text(page_text: str) -> dict:
    """
    Heuristics over page text to extract fields.
    """
    text = _clean(page_text)

    # Status (e.g., 'In development', 'Rolling out', 'Launched', etc.)
    status = _extract_field_by_label(text, [
        "Status", "Roadmap status", "Public roadmap status", "publicRoadmapStatus"
    ])

    # Release phase (e.g., 'General Availability', 'Preview')
    phase = _extract_field_by_label(text, [
        "Release phase", "Release Phase"
    ])

    # Targeted dates (e.g., 'September CY2025')
    targeted = _extract_field_by_label(text, [
        "Targeted Release", "Release", "Targeted date", "Targeted dates", "Timeline"
    ])

    # Cloud instance (e.g., 'Worldwide (Standard Multi-Tenant), GCC')
    cloud = _extract_field_by_label(text, [
        "Cloud instance", "Cloud Instance", "Cloud Instances"
    ])

    # Short description
    # Try to find a 'Description' block; else fall back to first paragraph after title
    desc = _extract_field_by_label(text, ["Description"])
    if not desc:
        # Look for a big paragraph-ish section
        m = re.search(r"(Description|Details)\s*:\s*(.+?)(?:\n[A-Z][^\n]{0,40}:|\Z)", text, flags=re.S)
        if m:
            desc = _clean(m.group(2))
        else:
            # fallback: first 300 chars of page content
            desc = _clean(text)[:300]

    return {
        "status": status,
        "phase": phase,
        "targeted": targeted,
        "cloud": cloud,
        "desc": desc,
    }

def _extract_title(page) -> str:
    # Prefer the visible H1; fallback to document.title
    try:
        h1 = page.locator("h1").first
        if h1 and h1.count() > 0:
            t = h1.inner_text().strip()
            if t:
                return _clean(t)
    except Exception:
        pass
    try:
        return _clean(page.title())
    except Exception:
        return ""

def fetch_ids_public(id_list: List[str]) -> List[List[str]]:
    """
    Use Playwright (Chromium) to fetch each roadmap item.
    Returns rows in TABLE_HEADERS shape.
    """
    rows: List[List[str]] = []
    if not id_list:
        return rows

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for fid in id_list:
            url = ROADMAP_URL.format(fid=fid)
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                # Retry with a looser wait
                try:
                    page.goto(url, timeout=45000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    # Give up on this ID
                    rows.append([fid, "", "", "", "", "", "", "", url])
                    continue

            # Extract title and product
            title = _extract_title(page)
            product, title_only = _split_title_product(title)

            # Full page text for heuristic parsing
            try:
                body_text = page.locator("body").inner_text()
            except Exception:
                body_text = ""

            fields = _guess_fields_from_text(body_text)

            # Construct row
            row = [
                fid,
                title if title else "",
                product,
                fields["status"],
                fields["phase"],
                fields["targeted"],
                fields["cloud"],
                fields["desc"],
                url,
            ]
            rows.append(row)

        context.close()
        browser.close()

    return rows
