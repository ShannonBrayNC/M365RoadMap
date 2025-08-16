from __future__ import annotations

import sys
import markdown


#!/usr/bin/env python3
import pathlib

def main() -> None:
    if len(sys.argv) != 3:
        print("usage: md_to_html.py <in.md> <out.html>")
        sys.exit(2)
    src = pathlib.Path(sys.argv[1])
    dst = pathlib.Path(sys.argv[2])
    md = src.read_text(encoding="utf-8")
    html = markdown.markdown(
        md,
        extensions=["tables", "toc", "sane_lists", "attr_list"],
        output_format="html5",
    )
    dst.write_text(html, encoding="utf-8")
    print(f"Wrote HTML: {dst}")

if __name__ == "__main__":
    main()





if __name__ == "__main__":
    main()
