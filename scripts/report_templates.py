#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class FeatureRecord:
    public_id: str
    title: str
    source: str
    product_workload: str
    status: str
    last_modified: str
    release_date: str
    cloud_instance: str
    official_roadmap_link: str
    message_id: str

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "FeatureRecord":
        # Map expected CSV headers → fields (case-stable from the fetch script)
        return cls(
            public_id=(row.get("PublicId") or "").strip(),
            title=(row.get("Title") or "").strip(),
            source=(row.get("Source") or "").strip(),
            product_workload=(row.get("Product_Workload") or "").strip(),
            status=(row.get("Status") or "").strip(),
            last_modified=(row.get("LastModified") or "").strip(),
            release_date=(row.get("ReleaseDate") or "").strip(),
            cloud_instance=(row.get("Cloud_instance") or "").strip(),
            official_roadmap_link=(row.get("Official_Roadmap_link") or "").strip(),
            message_id=(row.get("MessageId") or "").strip(),
        )

    def anchor_id(self) -> str:
        return f"id-{self.public_id}" if self.public_id else "id-unknown"


def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
    return (
        f"# {title}\n"
        f"_Generated {generated_utc}_\n\n"
        f"**Cloud filter:** {cloud_display}\n\n"
        "---\n"
    )


def make_tag_pills(products_str: str) -> str:
    if not products_str:
        return ""
    # Split on / , ; | and whitespace
    import re
    parts = [p for p in re.split(r"[\/,\|\;\s]+", products_str) if p]
    if not parts:
        return ""
    pills = " ".join(f"`{p}`" for p in parts)
    return f"**Products:** {pills}\n"


def render_table_of_contents(rows: Iterable[FeatureRecord]) -> str:
    items = []
    for r in rows:
        title = r.title or f"[{r.public_id}]"
        items.append(f"- [{title}](#{r.anchor_id()})")
    if not items:
        return ""
    return "## Table of Contents\n" + "\n".join(items) + "\n\n"


def _message_center_link(message_id: str) -> str:
    if not message_id:
        return ""
    # Admin portal deep link
    return f"https://admin.microsoft.com/Adminportal/Home#/messagecenter?id={message_id}"


def render_feature_markdown(rec: FeatureRecord) -> str:
    title = rec.title or f"[{rec.public_id}]"
    mc_link = _message_center_link(rec.message_id)
    source_bits = []
    if rec.official_roadmap_link:
        source_bits.append(f"[Roadmap]({rec.official_roadmap_link})")
    if mc_link:
        source_bits.append(f"[Message Center]({mc_link})")
    source_line = " · ".join(source_bits) if source_bits else ""

    meta = []
    if rec.status:
        meta.append(f"**Status:** {rec.status}")
    if rec.release_date:
        meta.append(f"**Release Date:** {rec.release_date}")
    if rec.cloud_instance:
        meta.append(f"**Cloud(s):** {rec.cloud_instance}")
    meta_line = "  \n".join(meta)

    products = make_tag_pills(rec.product_workload)

    lines = [
        f"### <a id=\"{rec.anchor_id()}\"></a> **{title}**",
    ]
    if source_line:
        lines.append(source_line)
    if meta_line:
        lines.append(meta_line)
    if products:
        lines.append(products.rstrip())

    # AI placeholder sections (kept minimal/clean)
    lines += [
        "",
        "**Summary**",
        "> (summary pending)",
        "",
        "**What’s changing**",
        "> (details pending)",
        "",
        "**Impact and rollout**",
        "> (impact pending)",
        "",
        "**Action items**",
        "> (actions pending)",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)
