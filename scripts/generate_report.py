#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Dict, Optional, Sequence
import os
from textwrap import dedent


# -----------------------------
# Model
# -----------------------------
@dataclass
class Row:
    PublicId: str
    Title: str
    Source: str
    Product_Workload: str
    Status: str
    LastModified: str
    ReleaseDate: str
    Cloud_instance: str
    Official_Roadmap_link: str
    MessageId: str

# -----------------------------
# Utilities
# -----------------------------
def _now_utc_iso() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _split_csv_like(s: Optional[str]) -> list[str]:
    if not s:
        return []
    # allow comma or pipe as separators
    parts = []
    for chunk in s.replace("|", ",").split(","):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts

def _cloud_display(clouds: Sequence[str]) -> str:
    if not clouds:
        return "General"
    return ", ".join(clouds)

def _choose_best_cloud_label(raw: str) -> str:
    # Accept whatever came from the CSV and normalize a little
    s = (raw or "").strip()
    return s if s else "—"

def _as_date(s: str) -> Optional[dt.date]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def _contains_any(text: str, needles: Iterable[str]) -> bool:
    t = (text or "").lower()
    return any(n.lower() in t for n in needles)

# -----------------------------
# IO
# -----------------------------
def read_master_csv(path: Path) -> list[Row]:
    rows: list[Row] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for d in r:
            rows.append(
                Row(
                    PublicId=d.get("PublicId", "").strip(),
                    Title=d.get("Title", "").strip(),
                    Source=d.get("Source", "").strip(),
                    Product_Workload=d.get("Product_Workload", "").strip(),
                    Status=d.get("Status", "").strip(),
                    LastModified=d.get("LastModified", "").strip(),
                    ReleaseDate=d.get("ReleaseDate", "").strip(),
                    Cloud_instance=d.get("Cloud_instance", "").strip(),
                    Official_Roadmap_link=d.get("Official_Roadmap_link", "").strip(),
                    MessageId=d.get("MessageId", "").strip(),
                )
            )
    return rows

def write_markdown(md: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

# -----------------------------
# Filtering / ordering
# -----------------------------
def filter_by_date(rows: list[Row], since: Optional[str], months: Optional[int]) -> list[Row]:
    if since:
        cutoff = _as_date(since)
    elif months:
        cutoff = (dt.date.today() - dt.timedelta(days=months * 30))
    else:
        cutoff = None

    if not cutoff:
        return rows

    out: list[Row] = []
    for r in rows:
        lm = _as_date(r.LastModified) or _as_date(r.ReleaseDate)
        if lm and lm >= cutoff:
            out.append(r)
    return out

def filter_by_cloud(rows: list[Row], clouds: Sequence[str]) -> list[Row]:
    if not clouds:
        return rows
    wanted = {c.strip().lower() for c in clouds if c.strip()}
    if not wanted:
        return rows

    def keep(r: Row) -> bool:
        if not r.Cloud_instance:
            return "worldwide" in wanted or "general" in wanted
        raw = r.Cloud_instance.lower()
        # simple matching against well-known names
        for c in wanted:
            if c in raw:
                return True
        return False

    return [r for r in rows if keep(r)]

def filter_by_products(rows: list[Row], products: Sequence[str]) -> list[Row]:
    if not products:
        return rows
    wanted = {p.strip().lower() for p in products if p.strip()}
    if not wanted:
        return rows

    def keep(r: Row) -> bool:
        hay = f"{r.Product_Workload} {r.Title}".lower()
        return any(p in hay for p in wanted)

    return [r for r in rows if keep(r)]

def order_by_forced_ids(rows: list[Row], forced_ids: Sequence[str]) -> list[Row]:
    if not forced_ids:
        return rows
    pos: dict[str, int] = {pid.strip(): i for i, pid in enumerate(forced_ids) if pid.strip()}
    # Keep natural order for non-forced items, but ensure forced ones appear first in given order.
    forced: list[Row] = []
    seen: set[str] = set()
    for pid in forced_ids:
        pid = pid.strip()
        if not pid:
            continue
        match = next((r for r in rows if r.PublicId == pid), None)
        if match:
            forced.append(match)
            seen.add(match.PublicId)
        else:
            # synth shell row to ensure it appears with a link in the report even if master was empty
            forced.append(
                Row(
                    PublicId=pid,
                    Title=f"[{pid}]",
                    Source="seed",
                    Product_Workload="",
                    Status="",
                    LastModified="",
                    ReleaseDate="",
                    Cloud_instance="",
                    Official_Roadmap_link=f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={pid}",
                    MessageId="",
                )
            )
            seen.add(pid)
    tail = [r for r in rows if r.PublicId not in seen]
    return forced + tail

# -----------------------------
# Synthesis
# -----------------------------
def _synth_summary(r: Row, deep: bool) -> str:
    product = r.Product_Workload or "Microsoft 365"
    title = r.Title or f"Roadmap item {r.PublicId}"
    if deep:
        lines = [
            f"{product}: {title}.",
            "This update is part of ongoing improvements delivered via Microsoft 365 service updates and the public roadmap.",
        ]
    else:
        lines = [f"{title} ({product})."]
    return " ".join(lines)

def _synth_whats_changing(r: Row, deep: bool) -> str:
    title = r.Title or ""
    verbs = []
    if _contains_any(title, ["new", "add", "introduc"]):
        verbs.append("introduces")
    if _contains_any(title, ["updated", "update", "change"]):
        verbs.append("updates")
    if not verbs:
        verbs = ["delivers"]

    if deep:
        return (
            f"This release {', and '.join(verbs)} the capability described in the title. "
            f"Customers will see this appear in the {r.Product_Workload or 'relevant'} experience once rollout reaches their tenant."
        )
    return f"This {verbs[0]} the feature described."

def _synth_impact(r: Row, deep: bool) -> str:
    clouds = _choose_best_cloud_label(r.Cloud_instance)
    rel = _as_date(r.ReleaseDate)
    when = rel.strftime("%Y-%m-%d") if rel else "TBD"
    target = r.Product_Workload or "workload"
    if deep:
        return (
            f"Admins and users of {target} should expect minor UX changes once enabled. "
            f"Rollout: {clouds}, starting {when}. Adoption and policy review may be required in some environments."
        )
    return f"Rollout to {clouds}; start {when}. Expect minor UX changes."

def _synth_actions(r: Row, deep: bool) -> str:
    items = [
        "Review the item in Message center (if applicable) and the official roadmap card.",
        "Communicate the change to affected users.",
        "Update training/help content as needed.",
    ]
    if deep:
        items.append("Evaluate policy/configuration implications in pilot before broad rollout.")
    mid = f"MC{r.MessageId}" if r.MessageId else ""
    link = r.Official_Roadmap_link or f"https://www.microsoft.com/microsoft-365/roadmap?searchterms={r.PublicId}"
    tail = f" Track via {mid} • Roadmap: {link}".strip()
    return "- " + "\n- ".join(items) + (f"\n\n{tail}" if tail else "")

def synthesize_sections(r: Row, deep: bool) -> dict[str, str]:
    return {
        "summary": _synth_summary(r, deep),
        "change": _synth_whats_changing(r, deep),
        "impact": _synth_impact(r, deep),
        "actions": _synth_actions(r, deep),
    }

# -----------------------------
# Rendering
# -----------------------------
def render_header(*, title: str, generated_utc: str, cloud_display: str) -> str:
    return (
        f"{title}\n"
        f"Generated {generated_utc}\n\n"
        f"{title} Generated {generated_utc} Cloud filter: {cloud_display}\n"
    )

def render_feature_markdown(r: Row, auto_fill: bool, deep: bool) -> str:
    cloud_lbl = _choose_best_cloud_label(r.Cloud_instance)
    status = r.Status or "—"
    rel = r.ReleaseDate or "—"
    lm = r.LastModified or "—"
    src = r.Source or "—"
    msg = f"MC{r.MessageId}" if r.MessageId else "—"
    link = r.Official_Roadmap_link or f"https://www.microsoft.com/microsoft-365/roadmap?filters=&searchterms={r.PublicId}"
    product = r.Product_Workload or "—"

    header = (
        f"\n[{r.PublicId}] {r.Title} "
        f"Product/Workload: {product} "
        f"Status: {status} "
        f"Cloud(s): {cloud_lbl} "
        f"Last Modified: {lm} "
        f"Release Date: {rel} "
        f"Source: {src} "
        f"Message ID: {msg} "
        f"Official Roadmap: {link}\n"
    )

    if auto_fill:
        synth = synthesize_sections(r, deep)
        body = (
            f"\nSummary\n\n{synth['summary']}\n\n"
            f"What’s changing\n\n{synth['change']}\n\n"
            f"Impact and rollout\n\n{synth['impact']}\n\n"
            f"Action items\n\n{synth['actions']}\n"
        )
    else:
        body = (
            "\nSummary (summary pending)\n\n"
            "What’s changing (details pending)\n\n"
            "Impact and rollout (impact pending)\n\n"
            "Action items (actions pending)\n"
        )
    return header + body



def _ai_available(args) -> bool:
    return not args.ai_off and bool(os.getenv("OPENAI_API_KEY"))

def _rule_based_sections(rec) -> tuple[str, str, str, str]:
    """
    Deterministic fallback content that requires no external calls.
    """
    title = rec.Title or f"[{rec.PublicId}]"
    product = rec.Product_Workload or "Microsoft 365"
    status = rec.Status or "—"
    clouds = rec.Cloud_instance or "General"
    lm = rec.LastModified or "—"
    rel = rec.ReleaseDate or "—"

    summary = (
        f"{product}: **{title}**.\n"
        f"This roadmap item is tracked under PublicId {rec.PublicId}. "
        f"Current status: {status}. Cloud: {clouds}. "
        f"Last modified {lm}; target/release date {rel}."
    )

    changes = (
        "Feature work is progressing based on roadmap telemetry and message center updates. "
        "Naming and scope may evolve as Microsoft ships iterative improvements."
    )

    impact = (
        "Low operational impact for most tenants during initial rollout. "
        "Expect gradual enablement via service-side flighting; timelines depend on ring and cloud. "
        "Admins should validate any policy side-effects in pilot rings."
    )

    actions = (
        "• Communicate the change to affected users/stakeholders.\n"
        "• Validate tenant- or workload-level policies that may influence rollout.\n"
        "• Update training/runbooks once the feature is observed in your tenant.\n"
        "• If applicable, monitor Message center post linked via the MessageId."
    )

    return summary, changes, impact, actions


def _ai_sections(args, rec) -> tuple[str, str, str, str] | None:
    """
    Best-effort AI summary using OpenAI if an API key is available.
    Falls back to None on any error (caller will use rule-based text).
    """
    if not _ai_available(args):
        return None

    try:
        from openai import OpenAI  # type: ignore[import-not-found]
        client = OpenAI()
        prompt = dedent(f"""
        Summarize this Microsoft 365 Roadmap item for an IT admin audience.
        Return four short sections titled exactly:
        Summary, What’s changing, Impact and rollout, Action items.

        PublicId: {rec.PublicId}
        Title: {rec.Title}
        Product/Workload: {rec.Product_Workload}
        Status: {rec.Status}
        Cloud(s): {rec.Cloud_instance}
        Last Modified: {rec.LastModified}
        Release Date: {rec.ReleaseDate}
        Official Link: {rec.Official_Roadmap_link}
        Message Center Id: {rec.MessageId}

        Keep each section 1–3 sentences. Avoid marketing fluff.
        """).strip()

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
        # naive split by section headers; if parse fails, return as summary + fallbacks
        sections = {"summary": "", "changes": "", "impact": "", "actions": ""}
        current = None
        for line in text.splitlines():
            l = line.strip()
            key = None
            if l.lower().startswith("summary"):
                key = "summary"
            elif l.lower().startswith("what’s changing") or l.lower().startswith("whats changing") or l.lower().startswith("what's changing"):
                key = "changes"
            elif l.lower().startswith("impact and rollout"):
                key = "impact"
            elif l.lower().startswith("action items"):
                key = "actions"

            if key:
                current = key
                # remove the header text after colon, keep any inline content
                colon = l.find(":")
                if colon >= 0 and colon < len(l) - 1:
                    sections[key] = l[colon+1:].strip()
                else:
                    sections[key] = ""
            elif current:
                sections[current] += ("\n" if sections[current] else "") + l

        # If parsing didn’t find good chunks, bail to None so we use the rule-based copy
        if not any(sections.values()):
            return None

        return (
            sections.get("summary") or "",
            sections.get("changes") or "",
            sections.get("impact") or "",
            sections.get("actions") or "",
        )
    except Exception:
        return None





# -----------------------------
# Main
# -----------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--master", required=True, help="CSV produced by fetch_messages_graph.py")
    p.add_argument("--out", required=True)
    p.add_argument("--since", default="")
    p.add_argument("--months", type=int, default=None)
    p.add_argument("--cloud", action="append", default=[], help="Cloud label(s); omit for General")
    p.add_argument("--products", default="", help="Comma/pipe separated product/workload filters; blank=all")
    p.add_argument("--forced-ids", default="", help="Comma-separated exact PublicId list; preserves order and creates shells if missing")
    p.add_argument("--no-auto-fill", action="store_true", help="Disable synthesized sections")
    p.add_argument("--ai-deep-dive", dest="deep", action="store_true", default=True, help="Richer synthesized content (default on)")
    p.add_argument("--no-ai-deep-dive", dest="deep", action="store_false", help="Turn off deep-dive verbiage")

    return p.parse_args(argv)

def main() -> None:
    args = parse_args()
    title = args.title
    master = Path(args.master)
    out_path = Path(args.out)

    clouds = args.cloud or []
    products = _split_csv_like(args.products)
    forced_ids = _split_csv_like(args.forced_ids)
    auto_fill = not args.no_auto_fill
    deep = bool(args.deep)

    rows = read_master_csv(master)
    # date filters
    rows = filter_by_date(rows, args.since, args.months)
    # cloud filter (treat no cloud as General)
    rows = filter_by_cloud(rows, clouds)
    # product filter
    rows = filter_by_products(rows, products)
    # ordering + synthesis shells for missing forced ids
    rows = order_by_forced_ids(rows, forced_ids)

    generated = _now_utc_iso()
    header = render_header(title=title, generated_utc=generated, cloud_display=_cloud_display(clouds))

    parts: list[str] = [render_header(title=args.title, generated_utc=generated, cloud_display=cloud_label)]
    parts.append(f"\nTotal features: {len(rows)}\n")

    for rec in rows:
        ai = _ai_sections(args, rec)
        if ai is None:
            ai = _rule_based_sections(rec)
        summary, changes, impact, actions = ai
        parts.append(
            render_feature_markdown(
                rec,
                summary=summary,
                changes=changes,
                impact=impact,
                actions=actions,
            )
        )


    md = "\n".join(parts).strip() + "\n"
    write_markdown(md, out_path)

if __name__ == "__main__":
    main()
