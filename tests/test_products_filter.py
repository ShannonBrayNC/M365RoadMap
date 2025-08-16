import csv
import io
import subprocess
import sys
from pathlib import Path


def _write_master(tmp: Path) -> Path:
    csv_text = """PublicId,Title,Product_Workload,Status,Cloud_instance,LastModified,ReleaseDate,Source,MessageId,Official_Roadmap_link
1001,Teams thing,Microsoft Teams,,General,2025-08-10,,graph,MC1,https://example/1001
1002,Intune item,Microsoft Intune,,GCC,2025-08-11,,graph,MC2,https://example/1002
1003,SharePoint feature,SharePoint Online,,DoD,2025-08-12,,graph,MC3,https://example/1003
"""
    p = tmp / "master.csv"
    p.write_text(csv_text, encoding="utf-8")
    return p


def test_products_filter(tmp_path: Path) -> None:
    master = _write_master(tmp_path)
    out_md = tmp_path / "out.md"

    # Filter to just "Teams|SharePoint"
    cmd = [
        sys.executable,
        str(Path("scripts") / "generate_report.py"),
        "--title",
        "Test",
        "--master",
        str(master),
        "--out",
        str(out_md),
        "--products",
        "Teams|SharePoint",
        "--cloud",
        "General|DoD",
    ]
    subprocess.run(cmd, check=True)

    text = out_md.read_text(encoding="utf-8")
    # Expect to see 1001 (Teams, General) and 1003 (SharePoint, DoD); not 1002 (Intune, GCC)
    assert "[1001]" in text
    assert "[1003]" in text
    assert "[1002]" not in text


def test_forced_ids_ordering(tmp_path: Path) -> None:
    master = _write_master(tmp_path)
    out_md = tmp_path / "out.md"

    cmd = [
        sys.executable,
        str(Path("scripts") / "generate_report.py"),
        "--title",
        "Test",
        "--master",
        str(master),
        "--out",
        str(out_md),
        "--forced-ids",
        "1003,1001",
    ]
    subprocess.run(cmd, check=True)

    text = out_md.read_text(encoding="utf-8")
    # First occurence should be 1003, then 1001
    first_1003 = text.find("[1003]")
    first_1001 = text.find("[1001]")
    assert 0 <= first_1003 < first_1001
