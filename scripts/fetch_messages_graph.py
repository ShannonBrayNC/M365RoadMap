# tests/test_products_filter.py
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path
import textwrap

def _write_master(tmp: Path) -> Path:
    rows = [
        {"id": "1001", "title": "Teams: Something", "product": "Microsoft Teams"},
        {"id": "1002", "title": "SharePoint: Thing", "product": "SharePoint"},
        {"id": "1003", "title": "Exchange: Other", "product": "Exchange Online"},
    ]
    p = tmp / "master.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id","title","product"])
        w.writeheader(); w.writerows(rows)
    return p

def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def test_products_filter(tmp_path: Path) -> None:
    master = _write_master(tmp_path)
    out_md = tmp_path / "out.md"
    cmd = [sys.executable, "scripts/generate_report.py",
           "--title", "Test",
           "--master", str(master),
           "--out", str(out_md),
           "--products", "Teams, SharePoint"]
    subprocess.check_call(cmd)
    txt = _read_text(out_md)
    assert "Teams: Something" in txt
    assert "SharePoint: Thing" in txt
    assert "Exchange: Other" not in txt

def test_forced_ids_ordering(tmp_path: Path) -> None:
    master = _write_master(tmp_path)
    out_md = tmp_path / "out.md"
    cmd = [sys.executable, "scripts/generate_report.py",
           "--title", "Test",
           "--master", str(master),
           "--out", str(out_md),
           "--forced-ids", "1003,1001"]
    subprocess.check_call(cmd)
    txt = _read_text(out_md)
    lines = [ln for ln in txt.splitlines() if ln.startswith("- **[")][:2]
    assert "1003" in lines[0], textwrap.dedent(f"Expected 1003 first, got:\n{lines}")
    assert "1001" in lines[1], textwrap.dedent(f"Expected 1001 second, got:\n{lines}")
