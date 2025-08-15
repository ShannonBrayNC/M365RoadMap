from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

try:
    import markdown  # type: ignore[import-untyped]
except Exception as exc:  # pragma: no cover
    raise SystemExit("Please: pip install markdown") from exc


_HTML_SHELL = """<!doctype html>
<html lang="en">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
body{{font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin:2rem; line-height:1.5}}
code, pre{{font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace}}
hr{{border:none;border-top:1px solid #e5e7eb;margin:2rem 0}}
h1,h2,h3{{line-height:1.2}}
.meta{{color:#6b7280}}
</style>
<body>
<h1>{title}</h1>
<p class="meta">Generated {generated} UTC</p>
<hr/>
{content}
</body>
</html>
"""


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("input", help="Markdown input path")
    p.add_argument("out", help="HTML output path")
    p.add_argument("--title", help="Optional HTML title", default="Roadmap Report")
    args = p.parse_args(argv)

    src = Path(args.input)
    out = Path(args.out)

    md_text = src.read_text(encoding="utf-8")
    html_body = markdown.markdown(md_text, extensions=["tables", "toc", "fenced_code"])  # type: ignore[no-untyped-call]

    generated = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M")
    html_full = _HTML_SHELL.format(title=args.title, generated=generated, content=html_body)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_full, encoding="utf-8")
    print(f"Wrote {out} ({len(html_full)} bytes)")


if __name__ == "__main__":
    main()
