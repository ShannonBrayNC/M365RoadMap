#!/usr/bin/env python3
from __future__ import annotations

# Allows `python scripts/md_to_html.py` from repo root
try:
    from scripts import _importlib_local  # noqa: F401
except Exception:
    pass

import argparse
import datetime as dt
from pathlib import Path

try:
    import markdown  # pip install markdown
except Exception:
    raise SystemExit("Please: pip install markdown")


HTML_WRAP = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji"; margin: 2rem; line-height: 1.5; }}
  h1,h2,h3,h4 {{ line-height: 1.2; }}
  code, pre {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }}
  .meta {{ color:#6b7280; font-size: 0.9rem; margin-bottom: 1rem; }}
  hr {{ border: 0; border-top: 1px solid #e5e7eb; margin: 2rem 0; }}
</style>
</head>
<body>
<div class="meta">Generated {generated}</div>
{body}
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="Markdown input path")
    ap.add_argument("--out", help="HTML output path")
    # Also allow positional fallback: md_to_html.py IN.md OUT.html
    ap.add_argument("positional", nargs="*", help=argparse.SUPPRESS)
    args = ap.parse_args()

    in_path: Path
    out_path: Path

    if args.input and args.out:
        in_path = Path(args.input)
        out_path = Path(args.out)
    else:
        if len(args.positional) != 2:
            raise SystemExit("Usage: md_to_html.py --input IN.md --out OUT.html  (or: md_to_html.py IN.md OUT.html)")
        in_path = Path(args.positional[0])
        out_path = Path(args.positional[1])

    md_text = in_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    generated = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html_text = HTML_WRAP.format(title=in_path.stem, body=html_body, generated=generated)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
