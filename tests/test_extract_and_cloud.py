from __future__ import annotations

import scripts.fetch_messages_graph as mod


def test_extract_and_include() -> None:
    fld = "General; GCC"
    assert mod.extract_clouds(fld) == {"General", "GCC"}
    assert mod.include_by_cloud(fld, {"General"}) is True
    assert mod.include_by_cloud(fld, {"GCCH"}) is False


def test_normalize_clouds() -> None:
    assert mod.normalize_clouds("Worldwide (Standard Multi-Tenant)") == {"General"}
    assert mod.normalize_clouds(["gcch", "dod"]) == {"GCC High", "DoD"}
