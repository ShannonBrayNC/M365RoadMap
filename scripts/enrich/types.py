from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any

@dataclass
class SourceLink:
    label: str
    url: str

@dataclass
class WebRef:
    title: str
    url: str
    snippet: Optional[str] = None

@dataclass
class EnrichedSources:
    roadmap: Optional[Dict[str, Any]] = None
    messageCenter: Optional[Dict[str, Any]] = None
    web: List[WebRef] = field(default_factory=list)

@dataclass
class EnrichedItem:
    id: str
    title: str
    product: str
    services: List[str]
    status: Optional[str] = None
    category: Optional[str] = None
    isMajor: Optional[bool] = None
    severity: Optional[str] = None
    lastUpdated: Optional[str] = None
    plannedStart: Optional[str] = None
    plannedEnd: Optional[str] = None
    summary: Optional[str] = None
    confidence: int = 0
    links: List[SourceLink] = field(default_factory=list)
    sources: EnrichedSources = field(default_factory=EnrichedSources)

    def to_json(self) -> Dict[str, Any]:
        def _coerce(obj):
            if hasattr(obj, "__dict__"):
                return asdict(obj)
            if isinstance(obj, list):
                return [ _coerce(x) for x in obj ]
            return obj
        return _coerce(self)

def dump_enriched(items: List[EnrichedItem]) -> List[Dict[str, Any]]:
    return [item.to_json() for item in items]
