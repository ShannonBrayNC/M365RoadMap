# scripts/parse_roadmap_markdown.py
import re
import json
import argparse
from pathlib import Path
from typing import List, Dict

H2 = re.compile(r"^##\s*(?:Feature\s*)?(?P<id>\d{4,9})\b[^\n]*$", re.I)
ID_INLINE = re.compile(r"\b(Roadmap\s*ID|Feature\s*ID)\s*:\s*(?P<id>\d{4,9})\b", re.I)
TITLE_INLINE = re.compile(r"^#+\s+(?P<title>.+)$")
CLOUD_INLINE = re.compile(r"\bClouds?\s*:\s*(?P<cloud>.+)", re.I)

def split_sections(lines: List[str]) -> List[List[str]]:
    out, cur = [], []
    for ln in lines:
        if ln.startswith("## "):
            if cur: out.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur: out.append(cur)
    return out

def parse_section(sec: List[str]) -> Dict:
    # detect id from H2 line
    id_ = None
    m = H2.match(sec[0].rstrip())
    if m:
        id_ = m.group("id")
    else:
        # fallback: look for Roadmap ID: ######
        for ln in sec[:10]:
            mm = ID_INLINE.search(ln)
            if mm:
                id_ = mm.group("id")
                break

    # title
    title = None
    # prefer the H2 text (strip leading "## " and ID)
    h2_text = sec[0].lstrip("#").strip()
    # remove leading ID patterns
    h2_text = re.sub(r"^(?:Feature\s*)?\d{4,9}\s*[:\-–—]\s*", "", h2_text).strip()
    if h2_text and not re.fullmatch(r"\d{4,9}", h2_text):
        title = h2_text

    # fallback titles from inner headings
    if not title:
        for ln in sec[:10]:
            mm = TITLE_INLINE.match(ln.strip())
            if mm:
                title = mm.group("title").strip()
                break

    # cloud (best effort)
    cloud = None
    for ln in sec[:20]:
        mm = CLOUD_INLINE.search(ln)
        if mm:
            cloud = mm.group("cloud").strip()
            break

    # summary: pull first non-empty paragraph after H2
    summary = None
    for ln in sec[1:]:
        s = ln.strip()
        if s and not s.startswith("#"):
            summary = s
            break

    return {
        "id": id_ or "",
        "title": title or "",
        "cloud": cloud or "",
        "summary": summary or "",
        "raw": "".join(sec).strip(),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--json")
    ap.add_argument("--months", type=int, default=None)
    ap.add_argument("--since", default=None)
    args = ap.parse_args()

    text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    # split by H2 sections (per-feature scaffold uses '##')
    sections = split_sections(lines)
    rows = [parse_section(sec) for sec in sections if sec and sec[0].startswith("## ")]

    # very defensive: filter rows that have an ID
    rows = [r for r in rows if r.get("id")]

    # Optional date filtering is a no-op here because dates are not in MD table;
    # leave hooks in case we add date tags later.

    if args.csv:
        import csv
        if not rows:
            print("No data to write to CSV.")
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "title", "cloud", "summary"])
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in ["id", "title", "cloud", "summary"]})
        print(f"CSV written to {args.csv}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON written to {args.json}")

if __name__ == "__main__":
    main()
