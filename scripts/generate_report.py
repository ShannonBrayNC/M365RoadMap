#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


# allow running this file directly:  python scripts/generate_report.py
try:
    from scripts.report_templates import FeatureRecord, render_feature_markdown
except ModuleNotFoundError:  # running from inside scripts/
    import os, sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))  # add repo root
    from scripts.report_templates import FeatureRecord, render_feature_markdown



from scripts.report_templates import FeatureRecord, render_feature_markdown


def _first(row: Dict[str, str], names: Iterable[str], default: str = "") -> str:
    for n in names:
        if n in row and str(row[n]).strip():
            return str(row[n]).strip()
    return default


ID_PATTERNS = [
    re.compile(r"\bRoadmap ID[:\s]*([0-9]{3,8})\b", re.I),
    re.compile(r"/details/([0-9]{3,8})\b", re.I),
    re.compile(r"/feature/([0-9]{3,8})\b", re.I),
    re.compile(r"\b(?:FR|ID)[:\s#]*([0-9]{3,8})\b", re.I),
]


def _extract_id(row: Dict[str, str]) -> str:
    id_ = _first(row, ["roadmap_id", "id", "feature_id"])
    if id_ and id_.isdigit():
        return id_
    hay = " ".join(
        [
            _first(row, ["roadmap_url", "link", "url"]),
            _first(row, ["body_html", "body", "description", "summary"]),
            _first(row, ["title", "name", "subject"]),
        ]
    )
    for pat in ID_PATTERNS:
        m = pat.search(hay or "")
        if m:
            return m.group(1)
    return ""


def _last_modified(row: Dict[str, str]) -> str:
    raw = _first(
        row,
        ["last_modified", "lastModifiedDateTime", "last_modified_utc", "modified", "updated"],
    )
    if not raw:
        return ""
    # Normalize to Z
    try:
        # Try common ISO forms
        ts = raw.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(ts).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return raw  # keep original if unknown


def _sources(row: Dict[str, str]) -> List[str]:
    s = _first(row, ["source", "source_type", "source_kind"]).lower()
    out: List[str] = []
    if "graph" in s:
        out.append("Graph")
    if "rss" in s:
        out.append("RSS")
    if "public" in s:
        out.append("Public JSON")
    if not out and s:
        out.append(s.title())
    return out


def _dedupe_keep_best(a: Dict[str, str], b: Dict[str, str]) -> Dict[str, str]:
    # Prefer richer title, latest modified
    pick = dict(a)
    if len(_first(b, ["title", "name", "subject"])) > len(_first(a, ["title", "name", "subject"])):
        pick = dict(b)
    ta = _last_modified(a)
    tb = _last_modified(b)
    if tb and (not ta or tb > ta):
        pick = dict(b)
    return pick


def build_features(rows: List[Dict[str, str]]) -> Tuple[List[FeatureRecord], int]:
    by_id: Dict[str, Dict[str, str]] = {}
    skipped = 0
    for r in rows:
        rid = _extract_id(r)
        if not rid:
            skipped += 1
            continue
        prev = by_id.get(rid)
        by_id[rid] = _dedupe_keep_best(prev, r) if prev else r

    feats: List[FeatureRecord] = []
    for rid, r in by_id.items():
        title = _first(r, ["title", "name", "subject"], default=f"Roadmap item {rid}")
        cloud = _first(
            r,
            ["cloud", "clouds", "tenant_cloud", "cloud_instance"],
        )
        status = _first(r, ["status", "state", "releasePhase", "release_phase"])
        fr = FeatureRecord(
            id=rid,
            title=title,
            cloud=cloud,
            status=status,
            last_modified=_last_modified(r),
            sources=_sources(r),
            tags=[],
        )
        feats.append(fr)

    # Sort by numeric ID desc by default
    feats.sort(key=lambda f: int(f.id), reverse=True)
    return feats, skipped


def read_master_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append({k: (v or "") for k, v in r.items()})
    return rows


def render_document(title: str, features: List[FeatureRecord]) -> str:
    parts: List[str] = []
    parts.append(f"# {title}\n")
    parts.append(f"_Generated {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n")
    parts.append("---\n")
    for fr in features:
        parts.append(render_feature_markdown(fr))
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Markdown report with strict scaffold")
    ap.add_argument("--title", required=True)
    ap.add_argument("--master", required=True, help="CSV produced by fetch_messages_graph.py")
    ap.add_argument("--out", required=True, help="Markdown output path")
    ap.add_argument("--no-window", action="store_true", help="unused (kept for CLI compatibility)")
    ap.add_argument("--since", default="", help="ignored here; applied later by parser")
    ap.add_argument("--months", default="", help="ignored here; applied later by parser")
    ap.add_argument("--cloud", action="append", default=[], help="ignored here; prose only")
    ap.add_argument("--forced-ids", default="", help="comma-separated IDs to forcibly include if present")
    args = ap.parse_args()

    rows = read_master_csv(Path(args.master))
    feats, skipped = build_features(rows)

    doc = render_document(args.title, feats)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")

    print(f"Wrote report: {out_path} (features={len(feats)}; skipped_no_id={skipped})")


if __name__ == "__main__":
    main()
