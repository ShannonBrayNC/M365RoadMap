#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List


def _as_list(x: Iterable[str] | None) -> List[str]:
    if not x:
        return []
    return [str(s).strip() for s in x if str(s).strip()]


def _md_escape(text: str) -> str:
    # Minimal escape to keep headings clean
    return (text or "").replace("\n", " ").strip()


@dataclass
class FeatureRecord:
    """
    Canonical “unit” that the generator emits and the parser expects.

    Heading (one per feature):
        ## [<id>] — <title>

    Immediately followed by a fenced meta block we can parse without external YAML:
        ```feature
        id: 123456
        title: Example feature
        cloud: Worldwide (Standard Multi-Tenant)
        status: Rolling out
        last_modified: 2025-08-15T04:12:00Z
        sources:
          - Graph
          - RSS
        tags:
          - SharePoint
          - Copilot
        ```
    Then fixed sections in this order (the parser can ignore prose but needs headings):
        ### What it is (confirmed)
        ### Why it matters
        ### What’s confirmed vs. inferred
        ### How you’ll use it (practical workflow)
        ### Cloud availability
        ### Notes
    """

    id: str
    title: str
    cloud: str = ""
    status: str = ""
    last_modified: str = ""
    sources: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    # Optional narrative; OK to leave blank
    summary_confirmed: str = ""
    why_it_matters: str = ""
    confirmed_vs_inferred: str = ""
    how_to_use: str = ""
    notes: str = ""

    def _meta_block(self) -> str:
        def list_block(name: str, items: List[str]) -> str:
            if not items:
                return f"{name}: []"
            lines = [f"{name}:"]
            for it in items:
                lines.append(f"  - {it}")
            return "\n".join(lines)

        parts = [
            f"id: {self.id}",
            f"title: {_md_escape(self.title)}",
            f"cloud: {_md_escape(self.cloud)}",
            f"status: {_md_escape(self.status)}",
            f"last_modified: {self.last_modified}",
            list_block("sources", _as_list(self.sources)),
            list_block("tags", _as_list(self.tags)),
        ]
        return "```feature\n" + "\n".join(parts) + "\n```"

    def to_markdown_section(self) -> str:
        h2 = f"## [{self.id}] — {_md_escape(self.title)}"
        meta = self._meta_block()

        def sec(h: str, body: str) -> str:
            body = (body or "").rstrip()
            if not body:
                body = "_(no notes)_"
            return f"### {h}\n{body}\n"

        # Provide very light defaults if prose is missing
        wc = self.summary_confirmed or "_(summary pending)_"
        wim = self.why_it_matters or "_(impact notes pending)_"
        cvi = self.confirmed_vs_inferred or "- **Confirmed:**\n- **Inferred:**"
        htu = self.how_to_use or "- _(usage notes pending)_"
        ca = f"- {self.cloud or 'Unspecified'}"
        notes = self.notes or ""

        return "\n".join(
            [
                h2,
                "",
                meta,
                "",
                sec("What it is (confirmed)", wc),
                sec("Why it matters", wim),
                sec("What’s confirmed vs. inferred", cvi),
                sec("How you’ll use it (practical workflow)", htu),
                sec("Cloud availability", ca),
                sec("Notes", notes),
            ]
        ) + "\n"


def render_feature_markdown(fr: FeatureRecord) -> str:
    return fr.to_markdown_section()
