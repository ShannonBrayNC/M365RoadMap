from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

from report_templates import FeatureRecord, render_feature_markdown, render_header

# Optional HTML parsing (fallback to regex if bs4/lxml aren’t available)
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate roadmap report markdown.")
    p.add_argument("--title", required=True, help="Report title")
    p.add_argument("--master", required=True, help="Master CSV (roadmap_report_master.csv)")
    p.add_argument("--out", required=True, help="Output markdown path")
    p.add_argument("--since", help="ISO date; include items modified on/after this date")
    p.add_argument("--months", type=int, help="Window in months from today (alternative to --since)")
    p.add_argument("--no-window", action="store_true", help="Disable date window filtering")
    p.add_argument("--cloud", help="Display filter (e.g., 'Worldwide (Standard Multi-Tenant)')")
    p.add_argument(
        "--messages-csv",
        default="output/graph_messages_master.csv",
        help="CSV containing Message Center bodies to enrich sections",
    )
    return p.parse_args()


# Map the terse cloud value to a friendly display
def display_cloud(cloud_raw: str | None) -> str:
    raw = (cloud_raw or "").strip()
    if not raw:
        return "—"
    mapping = {
        "General": "Worldwide (Standard Multi-Tenant)",
        "GCC": "GCC",
        "GCC High": "GCC High",
        "DoD": "DoD",
        "Worldwide (Standard Multi-Tenant)": "Worldwide (Standard Multi-Tenant)",
    }
    return mapping.get(raw, raw)


# Decide if a row matches the requested cloud filter
def cloud_selected(row_cloud: str | None, requested_display: str | None) -> bool:
    if not requested_display:
        return True
    # Normalize both sides
    rc = display_cloud(row_cloud)
    return rc.lower() == requested_display.strip().lower()


def load_csv(path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not Path(path).exists():
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "") for k, v in r.items()})
    return rows


def load_messages_bodies(messages_csv: str) -> Dict[str, str]:
    """
    Build a map MessageId -> HTML body (or best available).
    We look for common column names to be resilient across earlier dumps.
    """
    msg_rows = load_csv(messages_csv)
    body_map: Dict[str, str] = {}
    if not msg_rows:
        return body_map

    # Best-effort column discovery
    body_keys = ["Body", "body", "HtmlBody", "Html", "MC_Body", "MessageBody"]
    id_keys = ["MessageId", "Message ID", "Id", "MC_ID"]

    for r in msg_rows:
        mid = ""
        for k in id_keys:
            if k in r and r[k].strip():
                mid = r[k].strip()
                break
        if not mid:
            continue

        body = ""
        for bk in body_keys:
            if bk in r and r[bk].strip():
                body = r[bk]
                break
        # fallback to body preview (less ideal but better than nothing)
        if not body:
            for bk in ["BodyPreview", "Preview"]:
                if bk in r and r[bk].strip():
                    body = r[bk]
                    break

        if body:
            body_map[mid] = body
    return body_map


# -------- Message Center body -> section extraction --------

_HEADING_SYNONYMS: List[Tuple[str, str]] = [
    # target, regex to detect (case-insensitive)
    ("summary", r"^(message\s+summary|summary)\b"),
    ("changes", r"^(what'?s\s+changing|update\s+details|overview)\b"),
    ("impact", r"^(impact\s+and\s+rollout|how\s+this\s+will\s+affect.*|impact|rollout|timeline|when\s+this\s+will\s+happen)\b"),
    ("actions", r"^(action\s+items|what\s+you\s+need\s+to\s+do.*|what\s+you\s+can\s+do.*|next\s+steps|prepare)\b"),
]


def _html_to_text(html_in: str) -> str:
    if BeautifulSoup:
        soup = BeautifulSoup(html_in, "lxml")
        # Preserve list bullets as dashes
        for li in soup.find_all("li"):
            if li.string and li.string.strip():
                li.string.replace_with(f"- {li.get_text(strip=True)}")
        text = soup.get_text("\n")
    else:
        # crude fallback
        text = re.sub(r"<\s*br\s*/?>", "\n", html_in, flags=re.I)
        text = re.sub(r"<\s*/p\s*>", "\n\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _normalize_lines(txt: str) -> List[str]:
    # collapse excessive whitespace, keep bullets
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in txt.splitlines()]
    # drop empty
    return [ln for ln in lines if ln]


def extract_sections_from_mc_html(html_in: str) -> Dict[str, str]:
    """
    Heuristic sectioner:
      - turns HTML into lines
      - looks for known headings
      - everything under a heading goes into that bucket until next heading
    """
    txt = _html_to_text(html_in)
    lines = _normalize_lines(txt)

    buckets = {"summary": [], "changes": [], "impact": [], "actions": []}
    current = None

    def _is_heading(ln: str) -> str | None:
        for tgt, rx in _HEADING_SYNONYMS:
            if re.match(rx, ln.strip(), flags=re.I):
                return tgt
        return None

    for ln in lines:
        tgt = _is_heading(ln)
        if tgt:
            current = tgt
            continue
        if current:
            buckets[current].append(ln)

    # Fallbacks: if we never saw headings, use first paragraph as summary etc.
    flat = [ln for ln in lines if ln and not _is_heading(ln)]
    if not any(buckets.values()) and flat:
        # First 3-6 lines into summary
        buckets["summary"] = flat[:6]
        # Next 3 into changes if any
        if len(flat) > 6:
            buckets["changes"] = flat[6:9]

    def _fmt(key: str) -> str:
        if not buckets[key]:
            return ""
        # Join bullets nicely; keep existing dashes
        joined = "\n".join(buckets[key])
        # shrink long blocks into paragraphs with bullets where possible
        return joined

    return {
        "summary": _fmt("summary"),
        "whats_changing": _fmt("changes"),
        "impact_rollout": _fmt("impact"),
        "action_items": _fmt("actions"),
    }


# ---------------- Main pipeline ----------------

def main() -> None:
    args = parse_args()
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    master_rows = load_csv(args.master)
    msg_bodies = load_messages_bodies(args.messages_csv)

    # Date filtering
    def in_window(row: Dict[str, str]) -> bool:
        if args.no_window:
            return True
        # --months takes priority if provided
        if args.months:
            try:
                cutoff = dt.datetime.utcnow() - dt.timedelta(days=30 * args.months)
            except Exception:
                return True
            lm = (row.get("LastModified") or row.get("Modified") or "").split("T", 1)[0]
            try:
                lm_dt = dt.datetime.fromisoformat(lm)
                return lm_dt >= cutoff
            except Exception:
                return True
        if args.since:
            lm = (row.get("LastModified") or row.get("Modified") or "").split("T", 1)[0]
            try:
                lm_dt = dt.datetime.fromisoformat(lm)
                since_dt = dt.datetime.fromisoformat(args.since)
                return lm_dt >= since_dt
            except Exception:
                return True
        return True

    # Build features
    requested_cloud = (args.cloud or "").strip()
    total_before = len(master_rows)

    # Deduplicate by PublicId + MessageId (if present)
    seen_keys = set()
    feats: List[FeatureRecord] = []

    for r in master_rows:
        if not in_window(r):
            continue

        row_cloud_raw = r.get("Cloud_instance") or r.get("Cloud") or ""
        if requested_cloud:
            if not cloud_selected(row_cloud_raw, requested_cloud):
                continue

        pid = (r.get("PublicId") or r.get("RoadmapId") or r.get("Public ID") or "").strip()
        mid = (r.get("MessageId") or r.get("Message ID") or "").strip()
        key = f"{pid}::{mid or ''}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        body_html = msg_bodies.get(mid, "")
        sections = extract_sections_from_mc_html(body_html) if body_html else {
            "summary": "",
            "whats_changing": "",
            "impact_rollout": "",
            "action_items": "",
        }

        fr = FeatureRecord(
            public_id=pid or (r.get("Id") or "").strip(),
            title=(r.get("Title") or "").strip(),
            product_workload=(r.get("Product_Workload") or r.get("Product") or "").strip(),
            status=(r.get("Status") or "").strip(),
            clouds_display=display_cloud(row_cloud_raw),
            last_modified=(r.get("LastModified") or r.get("Modified") or "").strip(),
            release_date=(r.get("ReleaseDate") or "").strip(),
            source=(r.get("Source") or "").strip(),
            message_id=mid,
            official_url=(r.get("Official_Roadmap_link") or r.get("OfficialUrl") or "").strip(),
            summary=sections["summary"],
            whats_changing=sections["whats_changing"],
            impact_rollout=sections["impact_rollout"],
            action_items=sections["action_items"],
        )
        feats.append(fr)

    text_parts: List[str] = []
    cloud_display = requested_cloud or "All"
    text_parts.append(render_header(args.title, now, cloud_display, len(feats)))

    for fr in feats:
        text_parts.append(render_feature_markdown(fr))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(text_parts), encoding="utf-8")

    # Console stats
    cloud_hist = {"General": 0, "GCC": 0, "GCC High": 0, "DoD": 0}
    for r in feats:
        raw = (r.clouds_display or "").strip()
        # reverse-map display to raw for counters where reasonable
        if raw.startswith("Worldwide"):
            cloud_hist["General"] += 1
        elif raw in cloud_hist:
            cloud_hist[raw] += 1
    print(
        f"Wrote report: {args.out} (features={len(feats)})\n"
        f"[generate_report] rows: total={total_before} final={len(feats)} | "
        f"cloud_hist={cloud_hist} | selected={[requested_cloud or 'All']}"
    )


if __name__ == "__main__":
    main()
