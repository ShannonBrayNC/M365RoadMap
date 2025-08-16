# -*- coding: utf-8 -*-

from __future__ import annotations
from html import escape
from typing import Dict, List

EMDASH = "—"


def _pill(text: str) -> str:
    txt = escape(text or "").strip() or EMDASH
    return f"`{txt}`"


def _link(href: str, label: str) -> str:
    if not href:
        return escape(label)
    return f"[{escape(label)}]({href})"


def render_header(title: str, generated_utc: str, cloud_display: str) -> str:
    return (
        f"# {escape(title)}\n\n"
        f"Generated {escape(generated_utc)} · Cloud filter: {escape(cloud_display or 'General')}\n"
    )


def render_toc(rows: List[Dict[str, str]]) -> str:
    if not rows:
        return ""
    lines = ["\n**Total features: {n}**\n".format(n=len(rows)), "\n**Contents**"]
    for r in rows:
        pid = r.get("PublicId", "")
        title = r.get("Title", "") or f"[{pid}]"
        anchor = f"feature-{pid or abs(hash(title))}"
        lines.append(f"- [{escape(title)}](#{anchor})")
    return "\n".join(lines)


def _safe(d: Dict[str, str], key: str) -> str:
    return (d.get(key) or "").strip()


def render_feature_card(r: Dict[str, str]) -> str:
    pid = _safe(r, "PublicId")
    title = _safe(r, "Title") or f"[{pid}]"
    road = _safe(r, "Official_Roadmap_link")
    msgid = _safe(r, "MessageId")
    msg_link = f"https://admin.microsoft.com/adminportal/home#/MessageCenter/{msgid}" if msgid else ""
    prod = _safe(r, "Product_Workload")
    status = _safe(r, "Status")
    clouds = _safe(r, "Cloud_instance")
    lastmod = _safe(r, "LastModified") or EMDASH
    rel = _safe(r, "ReleaseDate") or EMDASH
    source = _safe(r, "Source") or EMDASH

    anchor = f"feature-{pid or abs(hash(title))}"

    # Title row + quick pills
    pills = " ".join([
        _pill(f"Status: {status or EMDASH}"),
        _pill(f"Release: {rel}"),
        _pill(f"Clouds: {clouds or EMDASH}"),
    ])
    prod_pill = f"\n{_pill(prod or 'Microsoft 365')}\n" if prod else ""

    # Two-column detail table
    rows = [
        ("Roadmap ID", pid or EMDASH),
        ("Product / Workload", prod or EMDASH),
        ("Last Modified", lastmod),
        ("Source", source or EMDASH),
        ("Status", status or EMDASH),
        ("Cloud(s)", clouds or EMDASH),
        ("Release Date", rel),
        ("Message ID", _link(msg_link, msgid) if msgid else EMDASH),
    ]

    tbl = [
        "",
        f"### **{escape(title)}**" + (f" ({_link(road, 'Official Roadmap')})" if road else ""),
        f"<a id='{anchor}'></a>",
        "",
        f"{pills}",
        f"{prod_pill}".rstrip(),
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for k, v in rows:
        tbl.append(f"| {escape(k)} | {v if v else EMDASH} |")

    # Summary block (with sources)
    sources_line = "Sources: " + " | ".join(
        s for s in [
            _link(road, "Official Roadmap") if road else "",
            _link(msg_link, "Message Center") if msgid else "",
        ] if s
    )
    tbl.extend([
        "",
        "**Summary**",
        "_summary pending_",
        "",
        sources_line,
        "",
        "<details><summary>What’s changing</summary>\n\ndetails pending\n\n</details>",
        "<details><summary>Impact and rollout</summary>\n\nimpact pending\n\n</details>",
        "<details><summary>Action items</summary>\n\nactions pending\n\n</details>",
        "",
        "---",
    ])
    return "\n".join(tbl)
