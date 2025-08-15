"""
Light sanity tests for graph_client surface.
All secrets below are obviously fake and are annotated for secret scanners.
"""

from __future__ import annotations

import base64
import json
import types
from pathlib import Path
from typing import Any

import pytest

import scripts.graph_client as graph_client

_FAKE_CFG: dict[str, Any] = {
    "tenant": "11111111-2222-3333-4444-555555555555",  # pragma: allowlist secret (fake GUID)
    "client_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",  # pragma: allowlist secret (fake GUID)
    "pfx_base64": base64.b64encode(b"fake-pfx-content").decode("ascii"),  # pragma: allowlist secret
    "pfx_password": "not-a-real-password",  # pragma: allowlist secret
}


def _write_cfg(tmp_path: Path, cfg: dict[str, Any]) -> Path:
    p = tmp_path / "graph_config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def test_module_imports() -> None:
    assert isinstance(graph_client, types.ModuleType)


def test_config_roundtrip(tmp_path: Path) -> None:
    p = _write_cfg(tmp_path, _FAKE_CFG)
    loaded = graph_client.load_config(str(p))
    assert loaded["tenant"] == _FAKE_CFG["tenant"]


def test_env_password_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = dict(_FAKE_CFG)
    cfg["pfx_password_env"] = "M365_PFX_PASSWORD"
    monkeypatch.setenv("M365_PFX_PASSWORD", "from-env")  # pragma: allowlist secret
    assert graph_client.get_pfx_password(cfg) == "from-env"


def test_pfx_base64_decodes_cleanly() -> None:
    b64 = _FAKE_CFG["pfx_base64"]
    base64.b64decode(b64, validate=True)  # no exception == pass


def test_acquire_token_presence_or_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    # This will not contact the network; acquire_token returns a fake token string
    tok = graph_client.acquire_token(dict(_FAKE_CFG))
    assert "fake_token_for_" in tok
