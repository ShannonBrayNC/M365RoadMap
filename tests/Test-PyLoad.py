# tests/Test-PyLoad.py
from __future__ import annotations

import sys
from pathlib import Path

def test_scripts_package_importable() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import scripts  # noqa: F401
    import scripts.graph_client  # noqa: F401

    pkg_file = Path(scripts.__file__).resolve()
    assert pkg_file.exists(), f"scripts package not found at {pkg_file}"
