# scripts/fetch_messages_graph.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


# ---------- Cloud helpers ----------

def normalize_clouds(clouds: Optional[Sequence[str]]) -> List[str]:
    """
    Map a variety of cloud labels into canonical forms used in filters/tests.
    Examples: GCC, GCC High, DoD, Worldwide (aka WW/Public/Commercial).
    """
    if not clouds:
        return []
    canon: List[str] = []
    for c in clouds:
        v = (c or "").strip().lower()
        if not v:
            continue
        if v in {"worldwide", "public", "commercial", "ww"}:
            canon.append("Worldwide")
        elif v in {"gcc", "usgcc"}:
            canon.append("GCC")
        elif v in {"gcc-high", "gcc high", "usgcc-high", "usgcc high"}:
            canon.append("GCC High")
        elif v in {"dod", "usdod"}:
            canon.append("DoD")
        else:
            # keep readable case for unknowns
            canon.append(c if any(ch.isupper() for ch in str(c)) else str(c).title())
    # de-duplicate, keep order
    seen: set[str] = set()
    out: List[str] = []
    for x in canon:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_clouds(item: Dict[str, Any]) -> List[str]:
    """
    Pull clouds from common fields across Graph MC items or public items.
    Looks at `clouds`, `Clouds`, `tags`, `Tags`, `categories`.
    """
    src = item or {}
    clouds = src.get("clouds") or src.get("Clouds") or []
    if isinstance(clouds, str):
        clouds = [x.strip() for x in clouds.split(",") if x.strip()]

    tags = src.get("tags") or src.get("Tags") or src.get("categories") or []
    if isinstance(tags, str):
        tags = [x.strip() for x in tags.split(",") if x.strip()]

    return normalize_clouds(list(clouds) + list(tags))


def include_by_cloud(item_clouds: Sequence[str] | None, allowed: Sequence[str] | None) -> bool:
    """
    True if item_clouds intersects allowed; if allowed empty/None, allow all.
    Accepts list or set for `allowed`.
    """
    if not allowed:
        return True
    allowed_norm = set(normalize_clouds(allowed))
    if not item_clouds:
        # permissive default when item doesn't specify clouds
        return True
    item_norm = set(normalize_clouds(item_clouds))
    return bool(item_norm & allowed_norm)


# ---------- Transform helpers ----------

def _match_product(prod: str, allowed: Sequence[str] | None) -> bool:
    if not allowed:
        return True
    p = (prod or "").lower()
    return any(a.strip().lower() in p for a in allowed if str(a).strip())


def transform_graph_messages(
    messages: Sequence[Dict[str, Any]],
    products: Sequence[str] | None = None,
    clouds: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    Normalize Graph Message Center items to a minimal common schema and
    filter by product + clouds.
    """
    out: List[Dict[str, Any]] = []
    for m in messages or []:
        services = m.get("services") or []
        product = services[0] if services else (m.get("product") or "")
        if not _match_product(product, products):
            continue
        m_clouds = extract_clouds(m)
        if not include_by_cloud(m_clouds, clouds):
            continue
        out.append(
            {
                "id": m.get("id", ""),
                "title": m.get("title", ""),
                "product": product,
                "services": services,
                "severity": m.get("severity") or "",
                "isMajorChange": bool(m.get("isMajorChange")),
                "lastModifiedDateTime": m.get("lastModifiedDateTime") or "",
                "clouds": m_clouds,
            }
        )
    return out


def transform_public_items(
    items: Sequence[Dict[str, Any]],
    products: Sequence[str] | None = None,
    clouds: Sequence[str] | None = None,  # present for parity; usually unused for Roadmap
) -> List[Dict[str, Any]]:
    """
    Normalize Roadmap/public items. Cloud filters typically don't apply to Roadmap,
    so we only product-filter and pass through.
    """
    out: List[Dict[str, Any]] = []
    for r in items or []:
        prod = r.get("product") or r.get("Product / Workload") or ""
        if not _match_product(prod, products):
            continue
        out.append(
            {
                "id": r.get("id")
                or r.get("roadmap_id")
                or r.get("Roadmap ID")
                or "",
                "title": r.get("title") or r.get("Title") or "",
                "product": prod,
                "status": r.get("status") or r.get("Status") or "",
                "clouds": extract_clouds(r),  # usually empty for Roadmap
            }
        )
    return out


def transform_rss(
    items: Sequence[Dict[str, Any]],
    products: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    Normalize fallback RSS items; filter by product text when provided (soft match
    against product or title).
    """
    out: List[Dict[str, Any]] = []
    for it in items or []:
        title = it.get("title") or ""
        prod = it.get("product") or ""
        if products and not any(
            (p.strip().lower() in (prod.lower() or title.lower()))
            for p in products
            if p.strip()
        ):
            continue
        out.append(
            {
                "id": it.get("id") or "",
                "title": title,
                "product": prod,
                "url": it.get("url") or it.get("link") or "",
            }
        )
    return out


__all__ = [
    "normalize_clouds",
    "extract_clouds",
    "include_by_cloud",
    "transform_graph_messages",
    "transform_public_items",
    "transform_rss",
]
