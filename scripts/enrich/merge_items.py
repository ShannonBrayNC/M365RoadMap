
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from dataclasses import asdict
import re

from .types import RoadmapItem, MCItem, EnrichedItem, SourceLink, WebRef

def _norm(s: Optional[str]) -> str:
    return (s or "").lower().strip()

def _token_set(s: str) -> set:
    return set(re.split(r"\W+", _norm(s))) - {""}

def title_similarity(a: str, b: str) -> float:
    # Jaccard similarity on token sets
    A, B = _token_set(a), _token_set(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    union = len(A | B)
    return inter / union if union else 0.0

_id_re = re.compile(r"(?:RM)?(\d{5,7})", re.I)

def extract_roadmap_ids(text: str) -> List[str]:
    return list({m.group(1) for m in _id_re.finditer(text or "")})

def mc_deeplink(mc_id: str) -> str:
    return f"https://admin.cloud.microsoft.com/#/MessageCenter/:/messages/{mc_id}"

def merge_items(
    roadmap: List[RoadmapItem],
    mc: List[MCItem],
    with_web: bool = False,
    web_search_fn: Optional[callable] = None,
) -> List[EnrichedItem]:

    # Index MC by RM ids mentioned
    index_by_rm: Dict[str, List[MCItem]] = {}
    for m in mc:
        for rid in extract_roadmap_ids(f"{m.title} {m.description or ''}"):
            index_by_rm.setdefault(rid, []).append(m)

    out: List[EnrichedItem] = []

    for r in roadmap:
        candidates: List[Tuple[MCItem, int]] = []

        # hard match by RM id
        if r.id and r.id in index_by_rm:
            for m in index_by_rm[r.id]:
                candidates.append((m, 70))

        # fuzzy by title and service overlap
        for m in mc:
            sim = title_similarity(r.title, m.title)
            score = int(round(sim * 50))
            if r.services and m.services:
                if any(_norm(s) in {_norm(x) for x in m.services} for s in r.services):
                    score += 15
            if (m.startDateTime or m.lastModifiedDateTime):
                score += 5
            if score >= 35:
                candidates.append((m, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        best = candidates[0] if candidates else None

        links = [SourceLink(label="Roadmap", url=r.url)] if r.url else []
        severity = None
        is_major = None
        last_updated = None

        if best:
            m, score = best
            links.append(SourceLink(label="Message Center", url=mc_deeplink(m.id)))
            severity = m.severity
            is_major = m.isMajorChange
            last_updated = m.lastModifiedDateTime

        web_refs: List[WebRef] = []
        if with_web and web_search_fn:
            q = f"{r.title} {r.product} site:microsoft.com OR site:learn.microsoft.com"
            try:
                web_refs = [WebRef(**w) for w in web_search_fn(q)]
                for w in web_refs:
                    links.append(SourceLink(label="Web", url=w.url))
            except Exception:
                web_refs = []

        item = EnrichedItem(
            id=r.id or (f"MC:{best[0].id}" if best else f"RM:{_norm(r.title)[:20]}"),
            title=r.title,
            product=r.product,
            services=r.services or ([r.product] if r.product else []),
            status=r.status,
            category=r.category,
            isMajor=is_major,
            severity=severity,
            lastUpdated=last_updated,
            plannedStart=None,
            plannedEnd=None,
            summary=r.summary,
            confidence=(best[1] if best else 0),
            links=links,
            sources={
                "roadmap": {"id": r.id, "url": r.url},
                "messageCenter": (
                    {"id": best[0].id, "url": mc_deeplink(best[0].id)} if best else None
                ),
                "web": [asdict(w) for w in web_refs] if web_refs else [],
            },
        )
        out.append(item)

    # Add MC-only
    rm_mc_ids = {i.sources.get("messageCenter", {}).get("id") for i in out if i.sources.get("messageCenter")}
    for m in mc:
        if m.id in rm_mc_ids:
            continue
        out.append(EnrichedItem(
            id=f"MC:{m.id}",
            title=m.title,
            product=(m.services[0] if m.services else ""),
            services=m.services or [],
            isMajor=m.isMajorChange,
            severity=m.severity,
            lastUpdated=m.lastModifiedDateTime,
            confidence=100,
            links=[SourceLink(label="Message Center", url=mc_deeplink(m.id))],
            sources={"messageCenter": {"id": m.id, "url": mc_deeplink(m.id)}},
        ))

    return out
