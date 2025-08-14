#!/usr/bin/env python3
"""
fallback_rss_api.py — Microsoft 365 Roadmap RSS/JSON fallback

Downloads the public JSON payload once from:
  https://www.microsoft.com/releasecommunications/api/v2/m365/rss
…then filters by the Roadmap feature IDs you pass in.

Outputs rows in your master schema:
| ID | Title | Product/Workload | Status | Release phase | Targeted dates | Cloud instance | Short description | Official Roadmap link |
"""
from __future__ import annotations
import json
from typing import Iterable, List, Dict, Any
import requests

MASTER_HEADERS = [
    "ID","Title","Product/Workload","Status","Release phase",
    "Targeted dates","Cloud instance","Short description","Official Roadmap link"
]

API_URL = "https://www.microsoft.com/releasecommunications/api/v2/m365/rss"

def _norm(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (list, tuple, set)):
        return ", ".join([_norm(i) for i in x if i is not None])
    s = str(x)
    # normalize whitespace and remove problematic pipe chars (tables)
    return " ".join(s.replace("\u200b", "").replace("|", " / ").split())

def _first(*vals: Any) -> str:
    for v in vals:
        if v:
            sv = _norm(v)
            if sv:
                return sv
    return ""

def _pluck(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def _string_list(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return ", ".join(_norm(v) for v in val if v)
    return _norm(val)

def fetch_rss_all() -> Dict[str, Any]:
    r = requests.get(API_URL, timeout=60)
    r.raise_for_status()
    return r.json()

def _extract_feature_id(item: Dict[str, Any]) -> str:
    # Try a variety of possible keys/locations
    # Common patterns observed: featureId, FeatureId, id
    return _first(
        _pluck(item, "featureId", "FeatureId", "id"),
        _pluck(item, "Id", "ID"),
    )

def _extract_title(item: Dict[str, Any]) -> str:
    return _first(
        _pluck(item, "title", "Title", "featureTitle", "FeatureTitle"),
        _pluck(item, "summary", "Summary"),
    )

def _extract_products(item: Dict[str, Any]) -> str:
    # Could be "products", "workload", "workloads", or nested tags
    return _first(
        _string_list(_pluck(item, "products", "Products", "workload", "Workload", "workloads", "Workloads")),
        _string_list(_pluck(item, "tags", "Tags")),
    )

def _extract_status(item: Dict[str, Any]) -> str:
    return _first(
        _pluck(item, "status", "Status", "publicRoadmapStatus", "PublicRoadmapStatus")
    )

def _extract_phase(item: Dict[str, Any]) -> str:
    return _first(
        _pluck(item, "releasePhase", "ReleasePhase")
    )

def _extract_targeted_dates(item: Dict[str, Any]) -> str:
    # often "GA", "GeneralAvailability", or "targeted", or "publicPreviewDate"
    return _first(
        _pluck(item, "targeted", "Targeted"),
        _pluck(item, "ga", "GA", "generalAvailability", "GeneralAvailability"),
        _pluck(item, "publicPreviewDate", "PublicPreviewDate"),
        _pluck(item, "releaseDate", "ReleaseDate"),
    )

def _extract_cloud_instance(item: Dict[str, Any]) -> str:
    # sometimes "cloudInstances" array, or a single "cloudInstance"
    ci = _pluck(item, "cloudInstances", "CloudInstances", "cloudInstance", "CloudInstance")
    return _string_list(ci)

def _extract_description(item: Dict[str, Any]) -> str:
    return _first(
        _pluck(item, "description", "Description", "shortDescription", "ShortDescription", "summary", "Summary")
    )

def _extract_official_link(item: Dict[str, Any], fid: str) -> str:
    # Prefer explicit link in payload, else build known roadmap URL
    L = _first(
        _pluck(item, "link", "Link", "moreInfoLink", "MoreInfoLink"),
        _pluck(item, "url", "Url", "URL"),
    )
    if L:
        return L
    if fid:
        return f"https://www.microsoft.com/en-us/microsoft-365/roadmap?id={fid}"
    return ""

def map_item_to_row(item: Dict[str, Any]) -> List[str]:
    fid = _norm(_extract_feature_id(item))
    title = _norm(_extract_title(item))
    product = _norm(_extract_products(item))
    status = _norm(_extract_status(item))
    phase = _norm(_extract_phase(item))
    targeted = _norm(_extract_targeted_dates(item))
    clouds = _norm(_extract_cloud_instance(item))
    desc = _norm(_extract_description(item))
    link = _extract_official_link(item, fid)

    return [fid, title, product, status, phase, targeted, clouds, desc, link]

def fetch_ids_rss(ids: Iterable[str]) -> List[List[str]]:
    ids_set = {str(i).strip() for i in ids if str(i).strip()}
    if not ids_set:
        return []
    data = fetch_rss_all()

    # The payload is versioned; try to find the array of items tolerant to shape.
    # Common keys: "value", "items", "Items", "results", etc.
    candidates = []
    for k in ("value", "items", "Items", "results", "Results", "data", "Data"):
        if isinstance(data.get(k), list):
            candidates = data[k]
            break
    if not candidates and isinstance(data, list):
        candidates = data

    rows: List[List[str]] = []
    for it in candidates or []:
        fid = _norm(_extract_feature_id(it))
        if not fid:
            continue
        if fid in ids_set:
            rows.append(map_item_to_row(it))

    return rows
