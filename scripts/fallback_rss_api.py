#!/usr/bin/env python3
"""
fallback_rss_api.py
Use the publicly available "RSS/JSON" programmatic feed as a resilient fallback.

Primary JSON endpoint (documented by Microsoft release comms):
    https://www.microsoft.com/releasecommunications/api/v2/m365/rss

Behavior:
- Try JSON first (fast and structured).
- If JSON fails, fall back to parsing XML using lxml/bs4.
- Filter by feature IDs and shape rows to TABLE_HEADERS.

Exported:
    fetch_ids_rss(id_list: list[str]) -> list[list[str]]
"""

from __future__ import annotations

import json
import re

import requests
from bs4 import BeautifulSoup

TABLE_HEADERS = [
    "ID",
    "Title",
    "Product/Workload",
    "Status",
    "Release phase",
    "Targeted dates",
    "Cloud instance",
    "Short description",
    "Official Roadmap link",
]

FEED_URL = "https://www.microsoft.com/releasecommunications/api/v2/m365/rss"


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.replace("\u200b", "").replace("|", " / ").split())


def _split_title_product(title: str) -> tuple[str, str]:
    if ":" in title:
        left, right = title.split(":", 1)
        return _clean(left), _clean(right)
    return "", _clean(title)


def _extract_feature_id(url_or_text: str) -> str:
    m = re.search(r"featureid=(\d+)", url_or_text, flags=re.I)
    return m.group(1) if m else ""


def _row_from_item(item: dict) -> list[str]:
    """
    Build a row from a JSON feed item (best-effort mapping).
    We expect keys like: title, link, description, categories, etc.
    """
    link = _clean(item.get("link") or item.get("url") or "")
    title = _clean(item.get("title") or "")
    desc = _clean(item.get("description") or item.get("summary") or "")
    fid = _extract_feature_id(link) or _extract_feature_id(title) or _extract_feature_id(desc)

    # Try to infer fields from categories/tags or text hints
    cats = item.get("categories") or item.get("tags") or []
    if isinstance(cats, str):
        categories = [cats]
    else:
        categories = [str(c) for c in cats if c]

    status = ""
    phase = ""
    targeted = ""
    cloud = ""

    # Try to detect status/phase hints
    hay = " ".join(categories + [title, desc])
    # Simple status hints
    for candidate in ["In development", "Rolling out", "Launched", "Cancelled", "Archived"]:
        if candidate.lower() in hay.lower():
            status = candidate
            break
    # Simple phase hints
    for candidate in ["General Availability", "Preview", "Targeted Release"]:
        if candidate.lower() in hay.lower():
            phase = candidate
            break
    # Targeted dates hints (e.g., 'September CY2025')
    m = re.search(r"([A-Z][a-z]+ CY20\d{2})", hay)
    if m:
        targeted = m.group(1)

    product, _title_only = _split_title_product(title)

    return [
        fid or "",  # ID
        title,  # Title
        product,  # Product/Workload
        status,  # Status
        phase,  # Release phase
        targeted,  # Targeted dates
        cloud,  # Cloud instance (not in feed; keep blank)
        desc,  # Short description
        link,  # Official Roadmap link
    ]


def _fetch_json() -> list[dict]:
    r = requests.get(FEED_URL, headers={"Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    # Some servers return text with JSON content-type; json.loads handles both
    return json.loads(r.text)


def _fetch_xml_items() -> list[dict]:
    r = requests.get(
        FEED_URL, headers={"Accept": "application/rss+xml, application/xml, */*"}, timeout=60
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "xml")
    items = []
    for it in soup.find_all("item"):
        items.append(
            {
                "title": it.title.text if it.title else "",
                "link": it.link.text if it.link else "",
                "description": it.description.text if it.description else "",
                "categories": [c.text for c in it.find_all("category")],
            }
        )
    return items


def fetch_ids_rss(id_list: list[str]) -> list[list[str]]:
    """
    Download the programmatic feed (JSON first, then XML) and filter by IDs.
    """
    want = {str(i).strip() for i in id_list if str(i).strip()}
    if not want:
        return []

    items: list[dict]
    rows: list[list[str]] = []

    # Try JSON first
    try:
        items = _fetch_json()
        # Some variants wrap in {'items': [...]}
        if isinstance(items, dict) and "items" in items:
            items = items["items"]
        if not isinstance(items, list):
            # Unexpected shape; degrade to XML
            raise ValueError("Unexpected JSON shape")
    except Exception:
        # Fallback to XML parse
        items = _fetch_xml_items()

    for it in items:
        row = _row_from_item(it)
        fid = row[0]
        if fid and fid in want:
            rows.append(row)

    return rows
