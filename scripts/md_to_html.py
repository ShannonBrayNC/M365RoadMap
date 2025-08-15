#!/usr/bin/env python3
import sys, pathlib, datetime
try:
    import markdown
except ImportError:
    sys.exit("Please: pip install markdown")

if len(sys.argv) < 3:
    sys.exit("Usage: md_to_html.py INPUT.md OUTPUT.html [title]")

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
title = sys.argv[3] if len(sys.argv) > 3 else src.stem

md_text = src.read_text(encoding="utf-8")
html_body = markdown.markdown(
    md_text,
    extensions=[
        "extra",          # tables, etc.
        "toc",            # table of contents
        "sane_lists",
        "admonition",
        "smarty",
        "nl2br",
    ],
)

css = """
body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;
     line-height:1.55; max-width:900px; margin:2rem auto; padding:0 1rem; color:#111}
h1,h2,h3{line-height:1.25} code,pre{font-family:ui-monospace,Consolas,monospace}
pre{background:#f6f8fa; padding:1rem; overflow:auto; border-radius:8px}
table{border-collapse:collapse; width:100%} th,td{border:1px solid #ddd; padding:6px}
th{background:#f3f4f6} a{color:#2563eb} hr{border:0; border-top:1px solid #e5e7eb; margin:2rem 0}
.toc{background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:1rem}
"""

html = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{css}</style>
<body>
<header>
  <h1>{title}</h1>
  <p style="color:#6b7280">Generated {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
  <hr>
</header>
{html_body}
</body></html>"""

dst.write_text(html, encoding="utf-8")
print(f"Wrote {dst} ({dst.stat().st_size} bytes)")
