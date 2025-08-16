
from __future__ import annotations
from dataclasses import dataclass, field, asdict
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
class RoadmapItem:
    id: Optional[str]
    title: str
    product: str = ""
    category: Optional[str] = None
    status: Optional[str] = None
    url: str = ""
    services: List[str] = field(default_factory=list)
    summary: Optional[str] = None

@dataclass
class MCItem:
    id: str
    title: str
    description: Optional[str] = None
    services: List[str] = field(default_factory=list)
    classification: Optional[str] = None
    severity: Optional[str] = None
    isMajorChange: Optional[bool] = None
    lastModifiedDateTime: Optional[str] = None
    startDateTime: Optional[str] = None
    endDateTime: Optional[str] = None

@dataclass
class EnrichedItem:
    id: str
    title: str
    product: str = ""
    services: List[str] = field(default_factory=list)
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
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        # dataclasses are nested; this ensures all nested dataclasses are converted
        def _convert(obj):
            if isinstance(obj, list):
                return [_convert(x) for x in obj]
            if hasattr(obj, "__dataclass_fields__"):
                return {k: _convert(v) for k, v in asdict(obj).items()}
            return obj
        return _convert(self)
