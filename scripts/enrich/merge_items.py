from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple, Set
import re
from dataclasses import asdict
from .types import EnrichedItem, EnrichedSources, SourceLink, WebRef

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()

def _title_similarity(a: str, b: str) -> float:
    A = set(_norm(a).split())
    B = set(_norm(b).split())
    if not A or not B: 
        return 0.0
    inter = len(A & B)
    union = len(A | B)
    return inter / max(1, union)

def _extract_rm_ids(text: str) -> List[str]:
    ids: Set[str] = set()
    for m in re.finditer(r"(?:Feature\s*ID|Roadmap\s*ID|RM)?\s*([0-9]{5,7})", text or "", re.I):
        ids.add(m.group(1))
    return sorted(ids)

def merge_items(roadmap: List[Dict[str, Any]], mc: List[Dict[str, Any]], web_hits: Optional[List[Dict[str, Any]]] = None, with_web: bool = False) -> List[EnrichedItem]:
    mc_by_id = {m.get("id"): m for m in mc}
    index_by_rm: Dict[str, List[Dict[str, Any]]] = {}
    for m in mc:
        body = f"{m.get('title','')} {m.get('description','')}"
        for rid in _extract_rm_ids(body):
            index_by_rm.setdefault(rid, []).append(m)

    out: List[EnrichedItem] = []

    for r in roadmap:
        r_id = str(r.get("id") or "").strip() or None
        r_title = r.get("title") or r.get("Title") or ""
        r_product = r.get("product") or r.get("Product") or r.get("Workload") or ""
        r_services = list(dict.fromkeys([s for s in r.get("services", []) or [r_product] if s]))  # pragma: no cover
        r_status = r.get("status") or r.get("Status")
        r_category = r.get("category") or r.get("Category")
        r_summary = r.get("summary") or r.get("Summary")
        r_url = r.get("url") or r.get("Url") or r.get("URL") or r.get("Link") or ""

        candidates: List[Tuple[Dict[str, Any], int]] = []

        if r_id and r_id in index_by_rm:
            for m in index_by_rm[r_id]:
                candidates.append((m, 70))

        for m in mc:
            ts = _title_similarity(r_title, m.get("title", ""))
            score = int(round(ts * 50))
            ms = [s.lower() for s in (m.get("services") or [])]
            if any(s.lower() in ms for s in r_services if isinstance(s, str)):
                score += 15
            if m.get("startDateTime") or m.get("lastModifiedDateTime"):
                score += 5
            if score >= 35:
                candidates.append((m, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        best = candidates[0][0] if candidates else None
        best_score = candidates[0][1] if candidates else 0

        links = []
        if r_url:
            links.append(SourceLink("Roadmap", r_url))
        severity = None
        is_major = None
        last_updated = None

        if best:
            mid = best.get("id")
            mc_url = f"https://admin.cloud.microsoft.com/#/MessageCenter/:/messages/{mid}"
            links.append(SourceLink("Message Center", mc_url))
            severity = best.get("severity")
            is_major = best.get("isMajorChange")
            last_updated = best.get("lastModifiedDateTime")

        web_list: List[WebRef] = []
        if with_web and web_hits:
            # attach any web hit whose title shares words with the roadmap title
            title_words = set(_norm(r_title).split())
            for w in web_hits:
                wtitle = w.get("title", "")
                if title_words & set(_norm(wtitle).split()):
                    web_list.append(WebRef(wtitle, w.get("url",""), w.get("snippet")))
                    links.append(SourceLink("Web", w.get("url","")))

        out.append(EnrichedItem(
            id = r_id or (best and f"MC:{best.get('id')}") or f"RM:{_norm(r_title)[:20]}",
            title = r_title,
            product = r_product,
            services = r_services or [r_product],
            status = r_status,
            category = r_category,
            isMajor = is_major,
            severity = severity,
            lastUpdated = last_updated,
            summary = r_summary,
            confidence = int(best_score or 0),
            links = links,
            sources = EnrichedSources(
                roadmap = {"id": r_id, "url": r_url} if r_url else {"id": r_id},
                messageCenter = {"id": best.get("id")} if best else None,
                web = web_list
            )
        ))

    # include MC-only items
    for m in mc:
        if any(x.sources.messageCenter and x.sources.messageCenter.get("id") == m.get("id") for x in out):
            continue
        mid = m.get("id")
        mc_url = f"https://admin.cloud.microsoft.com/#/MessageCenter/:/messages/{mid}"
        out.append(EnrichedItem(
            id=f"MC:{mid}",
            title=m.get("title",""),
            product=(m.get("services") or [""])[0],
            services=m.get("services") or [],
            isMajor=m.get("isMajorChange"),
            severity=m.get("severity"),
            lastUpdated=m.get("lastModifiedDateTime"),
            confidence=100,
            links=[SourceLink("Message Center", mc_url)],
            sources=EnrichedSources(messageCenter={"id": mid, "url": mc_url})
        ))

    return out
