# --- imports near top of file ---
import re
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Sequence, Set


# ---------- Cloud normalization helpers ----------

_SPLIT_RE = re.compile(r"[,\|;/]+")

_CLOUD_SYNONYMS = {
    "worldwide (standard multi-tenant)": "General",
    "worldwide": "General",
    "general": "General",
    "gcc": "GCC",
    "gcc high": "GCC High",
    "dod": "DoD",
    "government community cloud": "GCC",
}

def _split_cloud_tokens(val: str) -> List[str]:
    # split on common delimiters and strip
    return [p.strip() for p in _SPLIT_RE.split(val) if p.strip()]

def normalize_clouds(value: Any) -> Set[str]:
    """
    Normalize clouds into canonical labels (e.g., 'Worldwide' -> 'General').
    Accepts str, list/tuple/set[str], or None.
    Returns a set of normalized strings.
    """
    parts: List[str] = []

    if value is None or value == "":
        parts = []
    elif isinstance(value, str):
        parts = _split_cloud_tokens(value) if any(d in value for d in ",|;/") else [value.strip()]
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            if v is None:
                continue
            sv = str(v)
            if any(d in sv for d in ",|;/"):
                parts.extend(_split_cloud_tokens(sv))
            else:
                parts.append(sv.strip())
    else:
        parts = [str(value).strip()]

    # Map synonyms → canonical
    out: Set[str] = set()
    for p in parts or ["General"]:  # default to General if nothing provided
        key = p.lower()
        out.add(_CLOUD_SYNONYMS.get(key, p))
    return out


def _normalize_clouds_multi(value: Any) -> Set[str]:
    """Normalize when value may already be a collection of clouds."""
    if isinstance(value, (list, tuple, set)):
        acc: Set[str] = set()
        for v in value:
            acc |= normalize_clouds(v)
        return acc
    return normalize_clouds(value)


def include_by_cloud(item_clouds: Any, allowed: Any) -> bool:
    """
    True if the item's clouds intersect with the allowed filter.
    `allowed` may be str, list/tuple/set[str], or None.
    Missing item clouds are treated as {'General'}.
    """
    allowed_norm = _normalize_clouds_multi(allowed) if allowed else set()
    if not allowed_norm:
        return True
    item_norm = _normalize_clouds_multi(item_clouds) or {"General"}
    return bool(item_norm & allowed_norm)


# ---------- Product filter helper ----------

def _soft_product_match(title: str, product: str, products: Iterable[str] | None) -> bool:
    """
    Return True if no filter is provided, or if any product term appears
    in title or product (case-insensitive substring).
    """
    if not products:
        return True
    hay = f"{title} {product}".lower()
    for term in products:
        if term and str(term).lower() in hay:
            return True
    return False


# ---------- RSS normalization ----------

def transform_rss(
    items: Sequence[Dict[str, Any]] | Sequence[Any],
    products: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    Normalize fallback RSS items; filter by product text when provided (soft match
    against product or title). Tolerates string items by coercing to {'title': <str>}.
    """
    out: List[Dict[str, Any]] = []
    for it in (items or []):
        # Coerce non-mapping inputs safely
        if isinstance(it, str):
            it = {"title": it}
        elif not isinstance(it, Mapping):
            # Skip junk/unknown records
            continue

        title = str(it.get("title") or "")
        product = str(it.get("product") or it.get("workload") or "")
        link = it.get("link") or it.get("url") or ""

        if not _soft_product_match(title, product, products):
            continue

        clouds_norm = normalize_clouds(it.get("clouds"))

        out.append({
            "title": title,
            "product": product,
            "link": link,
            "clouds": clouds_norm,
            # keep any other fields you rely on:
            **{k: v for k, v in it.items() if k not in {"title", "product", "workload", "link", "url", "clouds"}},
        })
    return out
