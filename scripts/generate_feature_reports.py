#!/usr/bin/env python3
"""
Generate a per-feature Markdown report from the master list,
optionally enriching from public Roadmap JSON and auto-filling
tailored narrative sections via OpenAI.

Examples:
  # simple (no AI)
  python scripts/generate_feature_reports.py \
    --title "Roadmap Feature Report" \
    --master output/roadmap_report_master.csv \
    --fetch-public \
    --out output/roadmap_report.md

  # with AI (needs OPENAI_API_KEY)
  python scripts/generate_feature_reports.py \
    --master output/roadmap_report_master.csv \
    --fetch-public \
    --use-openai --model gpt-4o-mini \
    --prompt prompts/feature_summarize_tailored.md \
    --out output/roadmap_report.md
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import textwrap
from pathlib import Path

PUBLIC_ROADMAP_JSON = "https://www.microsoft.com/releasecommunications/api/v1/m365"
ID_RE = re.compile(r"(\d{6})")


def _read_csv(path: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _read_json(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "value" in data:
        return data["value"]
    raise ValueError("Unsupported JSON shape")


def _nice_date(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    try:
        from dateutil import parser as dateparser  # lazy import

        return dateparser.isoparse(s).date().isoformat()
    except Exception:
        return s[:10]


def _first_nonempty(*vals: str) -> str:
    for v in vals:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _extract_id_from_any(d: dict[str, str]) -> str | None:
    for key in ("PublicId", "FeatureId", "Feature ID", "Roadmap Id", "RoadmapID"):
        v = d.get(key)
        if v and v.isdigit() and len(v) == 6:
            return v
    for key in ("Official_Roadmap_link", "Official Roadmap link", "URL", "Link"):
        v = d.get(key)
        if v:
            m = ID_RE.search(v)
            if m:
                return m.group(1)
    for v in d.values():
        m = ID_RE.search(str(v))
        if m:
            return m.group(1)
    return None


def _load_public_index(fetch: bool, cache_path: str | None) -> dict[str, dict[str, str]]:
    items: list[dict[str, str]] = []
    if cache_path and Path(cache_path).exists():
        try:
            items = _read_json(cache_path)
        except Exception:
            items = []
    if fetch or not items:
        import requests

        s = requests.Session()
        r = s.get(PUBLIC_ROADMAP_JSON, timeout=(5, 30))
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("value") or data.get("items") or []
    idx: dict[str, dict[str, str]] = {}
    for it in items:
        low = {k.lower(): k for k in it.keys()}
        fid = ""
        for key in ("featureid", "publicid", "id", "feature_id"):
            k = low.get(key)
            if k and str(it.get(k) or "").isdigit():
                fid = str(it[k])
                break
        if fid:
            idx[fid] = it
    return idx


def _get_public_field(item: dict[str, str], *cands: str) -> str:
    if not item:
        return ""
    low = {k.lower(): k for k in item}
    for c in cands:
        k = low.get(c.lower())
        if k and item.get(k):
            return str(item[k])
    for c in cands:
        for lk, k in low.items():
            if c.lower() in lk and item.get(k):
                return str(item[k])
    return ""


def _load_prompt(path: str | None) -> tuple[str, str]:
    default_system = "You are a precise Microsoft 365 technical writer. Be factual and concise."
    default_user = textwrap.dedent("""\
    Using ONLY the supplied data, draft these sections in Markdown:

    ### What it is (summary)
    - 2–3 bullets

    ### Why it matters
    - 2 bullets focused on user/admin impact

    ### Confirmed vs inferred
    - List what is confirmed from the data
    - List what is inferred/unknown

    ### How you’ll use it
    - 3–5 bullets describing user/admin workflow

    ### Admin & governance
    - Policies, retention, toggles (note unknown items clearly)

    ### Comparison with adjacent features
    - Compare with related capabilities (bullets)

    ### Day-one checklist
    - 3–5 bullets for roll-out readiness

    ### Open items to verify
    - 3 bullets with concrete follow-ups

    Do not invent facts. If a point is unknown, say "Unknown".
    End with nothing extra.

    DATA:
    {{DATA}}
    """)
    if not path or not Path(path).exists():
        return default_system, default_user
    txt = Path(path).read_text(encoding="utf-8")
    parts = txt.split("\n---\n", 1)
    return (
        (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (default_system, txt.strip())
    )


def _summarize_with_openai(model: str, sys_prompt: str, user_prompt: str) -> str:
    try:
        from openai import OpenAI  # pip install openai>=1.40.0
    except Exception as e:
        return f"_OpenAI client not installed: {e}_"
    client = OpenAI()  # reads OPENAI_API_KEY
    try:
        rsp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        if getattr(rsp, "output_text", None):
            return str(rsp.output_text).strip()
        parts = []
        for p in getattr(rsp, "output", []) or []:
            for c in getattr(p, "content", []) or []:
                if getattr(c, "text", None):
                    parts.append(c.text)
        return "\n".join(parts).strip() if parts else str(rsp)[:2000]
    except Exception as e:
        return f"_OpenAI summarization failed: {e}_"


def build_tailored_section(
    fid: str, base: dict[str, str], pub: dict[str, str] | None, ai_md: str | None
) -> str:
    title = _first_nonempty(base.get("Title", ""), _get_public_field(pub or {}, "title"))
    workload = _first_nonempty(
        base.get("Product_Workload", ""),
        base.get("Product/Workload", ""),
        _get_public_field(pub or {}, "workload", "product"),
    )
    status = _first_nonempty(
        base.get("Status", ""), _get_public_field(pub or {}, "status", "state")
    )
    release = _first_nonempty(
        base.get("ReleaseDate", ""), _get_public_field(pub or {}, "releasedate", "startdate")
    )
    cloud = _first_nonempty(
        base.get("Cloud_instance", ""), _get_public_field(pub or {}, "cloud instance", "cloud")
    )
    link = f"https://www.microsoft.com/microsoft-365/roadmap?searchterms={fid}"
    desc = _get_public_field(pub or {}, "description", "summary", "details")

    header = [f"## {fid} — {title or '(untitled)'}", ""]
    basics = []
    if workload:
        basics.append(f"**Product/Workload:** {workload}")
    if status:
        basics.append(f"**Status:** {status}")
    if release:
        basics.append(f"**Target window/date:** {_nice_date(release)}")
    if cloud:
        basics.append(f"**Cloud(s):** {cloud}")
    basics.append(f"**Official Roadmap:** {link}")
    if desc:
        basics.append(f"\n> {desc.strip()}")
    preface = "\n".join(header + basics) + "\n\n"

    if ai_md:
        return preface + ai_md.strip() + "\n"

    return (
        preface
        + textwrap.dedent("""
    ### What it is (summary)
    _Add 2–3 bullets from official copy._

    ### Why it matters
    _Add org-specific rationale (2 bullets)._

    ### Confirmed vs inferred
    - **Confirmed:** title/status/date/official link present
    - **Inferred/Unknown:** details not yet published

    ### How you’ll use it
    _Add concrete steps for your org._

    ### Admin & governance
    _Retention, data residency, toggles, policies._

    ### Comparison with adjacent features
    _List closely related features and differences._

    ### Day-one checklist
    - Pilot group identified
    - Policies validated
    - Comms & quick-start drafted

    ### Open items to verify
    - Pending doc link / GA notes
    - Tenant controls / licensing nuances
    - Support boundaries
    """).strip()
        + "\n"
    )


def main():
    ap = argparse.ArgumentParser(
        description="Generate tailored per-feature Markdown with optional enrichment/AI."
    )
    ap.add_argument("--title", default="Roadmap Feature Report")
    ap.add_argument("--master", required=True, help="Path to <TITLE>_master.csv OR .json")
    ap.add_argument("--public-cache", help="Optional path to cached public JSON")
    ap.add_argument(
        "--fetch-public", action="store_true", help="Fetch official Roadmap JSON v1 for enrichment"
    )
    ap.add_argument(
        "--use-openai", action="store_true", help="Use OpenAI to auto-fill tailored sections"
    )
    ap.add_argument("--model", default="gpt-4o-mini", help="OpenAI model (when --use-openai)")
    ap.add_argument(
        "--prompt", default="prompts/feature_summarize_tailored.md", help="Prompt file (optional)"
    )
    ap.add_argument("--out", required=True, help="Output Markdown file")
    args = ap.parse_args()

    p = Path(args.master)
    if not p.exists():
        raise SystemExit(f"Master file not found: {p}")

    rows = _read_json(str(p)) if p.suffix.lower() == ".json" else _read_csv(str(p))

    public_index: dict[str, dict[str, str]] = {}
    if args.fetch_public or (args.public_cache and Path(args.public_cache).exists()):
        public_index = _load_public_index(args.fetch_public, args.public_cache)

    sys_prompt, user_prompt = _load_prompt(args.prompt) if args.use_openai else ("", "")

    features: dict[str, dict[str, str]] = {}
    for r in rows:
        fid = _extract_id_from_any(r)
        if not fid:
            continue
        if fid not in features or (not features[fid].get("Title") and r.get("Title")):
            features[fid] = r

    sections: list[str] = []
    for fid, base in sorted(features.items(), key=lambda kv: kv[0]):
        ai_md = None
        if args.use_openai:
            blob = {
                "FeatureId": fid,
                "Title": _first_nonempty(base.get("Title", ""), ""),
                "Product_Workload": _first_nonempty(
                    base.get("Product_Workload", ""), base.get("Product/Workload", "")
                ),
                "Status": base.get("Status", ""),
                "ReleaseDate": base.get("ReleaseDate", ""),
                "Cloud_instance": base.get("Cloud_instance", ""),
                "Official_Roadmap_link": f"https://www.microsoft.com/microsoft-365/roadmap?searchterms={fid}",
            }
            pub = public_index.get(fid)
            if pub:

                def add(k, v):
                    if v:
                        blob[k] = v

                add(
                    "Public.description",
                    _get_public_field(pub, "description", "summary", "details"),
                )
                add("Public.workload", _get_public_field(pub, "workload", "product"))
                add("Public.status", _get_public_field(pub, "status", "state"))
                add("Public.releaseDate", _get_public_field(pub, "releasedate", "startdate"))
                add("Public.cloud", _get_public_field(pub, "cloud instance", "cloud"))
            up = user_prompt.replace("{{DATA}}", json.dumps(blob, ensure_ascii=False, indent=2))
            ai_md = _summarize_with_openai(args.model, sys_prompt, up)
        sections.append(build_tailored_section(fid, base, public_index.get(fid), ai_md))

    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    doc = f"# {args.title}\n\n_Generated {now}_\n\n" + "\n---\n\n".join(sections) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(doc, encoding="utf-8")
    print(f"Wrote {args.out} with {len(sections)} features.")


if __name__ == "__main__":
    sys.exit(main())
