# tests/test_graph_client.py
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
import datetime as dt

import pytest

# Import the module under test and the public classes
# Assumes scripts/ is a package (scripts/__init__.py exists)
import scripts.graph_client as gcmod
from scripts.graph_client import GraphClient, GraphConfig


# ----------------------
# Helpers / Fakes
# ----------------------
class FakePrivateKey:
    def private_bytes(self, *, encoding=None, format=None, encryption_algorithm=None) -> bytes:  # noqa: D401
        return b"-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n"


class FakeCert:
    def fingerprint(self, algo) -> bytes:  # noqa: D401
        # return bytes; caller will .hex()
        return b"\x01\x02\xab\xcd"


class FakeMSALApp:
    def __init__(self, *, client_id: str, authority: str, client_credential: Dict[str, str]):
        self.client_id = client_id
        self.authority = authority
        self.client_credential = client_credential
        self.calls: List[Dict[str, Any]] = []

    def acquire_token_for_client(self, *, scopes: List[str]):
        self.calls.append({"scopes": scopes})
        # Typical MSAL response
        return {"access_token": "AT_FAKE", "expires_in": 3600}


# ----------------------
# Fixtures
# ----------------------
@pytest.fixture(autouse=True)
def ensure_clean_env(monkeypatch):
    # Prevent accidental leakage from developer shells
    for k in [
        "GRAPH_TENANT_ID",
        "TENANT",
        "GRAPH_CLIENT_ID",
        "CLIENT",
        "M365_PFX_BASE64",
        "PFX_B64",
        "M365_PFX_PASSWORD",
        "PFX_PASSWORD_ENV",
        "GRAPH_BASE",
        "AUTHORITY_BASE",
    ]:
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def tmp_cfg_file(tmp_path: Path) -> Path:
    # Minimal valid config with placeholders; base64 contents are arbitrary here
    cfg = {
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "client_id": "11111111-1111-1111-1111-111111111111",
        "pfx_base64": "UFhYUlhGWQ==",  # arbitrary base64 -> b"PXXRXFY"
        "pfx_password_env": "M365_PFX_PASSWORD",
        "graph_base": "https://graph.microsoft.com/v1.0",
        "authority_base": "https://login.microsoftonline.com",
    }
    p = tmp_path / "graph_config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


# ----------------------
# Tests: config loading
# ----------------------
def test_config_from_file_reads_values(tmp_cfg_file: Path):
    cfg = GraphConfig.from_file(str(tmp_cfg_file))
    assert cfg.tenant_id.startswith("0000")
    assert cfg.client_id.startswith("1111")
    assert cfg.pfx_base64
    assert cfg.graph_base.endswith("/v1.0")
    assert cfg.authority_base.endswith("microsoftonline.com")


def test_config_from_env_reads_both_prefixes(monkeypatch):
    # Support GRAPH_* and short names (TENANT/CLIENT/PFX_B64)
    monkeypatch.setenv("GRAPH_TENANT_ID", "t-guid")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "c-guid")
    monkeypatch.setenv("M365_PFX_BASE64", "QUJDCg==")
    monkeypatch.setenv("PFX_PASSWORD_ENV", "M365_PFX_PASSWORD")
    monkeypatch.setenv("M365_PFX_PASSWORD", "secret")
    cfg = GraphConfig.from_env()
    assert cfg.tenant_id == "t-guid"
    assert cfg.client_id == "c-guid"
    assert cfg.pfx_password_env == "M365_PFX_PASSWORD"
    assert cfg.pfx_base64 == "QUJDCg=="


def test_config_from_env_missing_raises(monkeypatch):
    with pytest.raises(RuntimeError):
        GraphConfig.from_env()


# ----------------------
# Tests: auth + token + scope
# ----------------------
def test_build_app_uses_pkcs12_msal_and_scope(monkeypatch, tmp_cfg_file: Path):
    # Arrange: patch PKCS#12 loader and MSAL
    fake_key = FakePrivateKey()
    fake_cert = FakeCert()

    def fake_b64decode(b64: str) -> bytes:  # noqa: ANN001
        return b"FAKE_PFX_BYTES"

    def fake_load_pkcs12(pfx_bytes: bytes, password: bytes | None):  # noqa: ANN001
        assert pfx_bytes == b"FAKE_PFX_BYTES"
        assert password == b"secret"
        return fake_key, fake_cert, None

    msal_calls: Dict[str, Any] = {}

    def fake_msal_app(**kw):  # noqa: ANN001
        app = FakeMSALApp(**kw)
        msal_calls["app"] = app
        return app

    monkeypatch.setenv("M365_PFX_PASSWORD", "secret")
    monkeypatch.setattr(gcmod.base64, "b64decode", fake_b64decode)
    monkeypatch.setattr(gcmod, "load_key_and_certificates", fake_load_pkcs12)
    monkeypatch.setattr(gcmod.msal, "ConfidentialClientApplication", fake_msal_app)

    cfg = GraphConfig.from_file(str(tmp_cfg_file))
    cli = GraphClient(cfg)

    # Act: acquire a token (this forces _build_app())
    tok = cli._acquire_token()

    # Assert: token, scope, and client credential shape
    assert tok == "AT_FAKE"
    app: FakeMSALApp = msal_calls["app"]
    # Scope is derived from graph_base root (no /v1.0), then '/.default'
    assert app.calls[0]["scopes"] == ["https://graph.microsoft.com/.default"]
    cred = app.client_credential
    assert "private_key" in cred and "thumbprint" in cred
    assert isinstance(cred["thumbprint"], str) and cred["thumbprint"]  # from cert.fingerprint().hex()


def test_acquire_token_is_cached(monkeypatch, tmp_cfg_file: Path):
    # Patch PKCS12 + MSAL as above, but count acquire_token_for_client calls
    fake_key = FakePrivateKey()
    fake_cert = FakeCert()

    def fake_load_pkcs12(pfx_bytes: bytes, password: bytes | None):  # noqa: ANN001
        return fake_key, fake_cert, None

    class CountingMSAL(FakeMSALApp):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.count = 0

        def acquire_token_for_client(self, *, scopes: List[str]):  # noqa: D401
            self.count += 1
            return super().acquire_token_for_client(scopes=scopes)

    app_holder: Dict[str, Any] = {}

    def fake_msal_app(**kw):  # noqa: ANN001
        app = CountingMSAL(**kw)
        app_holder["app"] = app
        return app

    # Freeze time so cache path is taken (remaining > 120s)
    t = {"now": 1000.0}

    def fake_time():
        return t["now"]

    monkeypatch.setenv("M365_PFX_PASSWORD", "pw")
    monkeypatch.setattr(gcmod, "load_key_and_certificates", fake_load_pkcs12)
    monkeypatch.setattr(gcmod.msal, "ConfidentialClientApplication", fake_msal_app)
    monkeypatch.setattr(time, "time", fake_time)

    cfg = GraphConfig.from_file(str(tmp_cfg_file))
    cli = GraphClient(cfg)

    # First call acquires token
    cli._acquire_token()
    # Advance a little but keep within expiry window (3600s - 10s > 120s)
    t["now"] += 10
    # Second call should use cached token (no extra MSAL call)
    cli._acquire_token()

    app: CountingMSAL = app_holder["app"]
    assert app.count == 1  # only called once


# ----------------------
# Tests: data fetch / pagination
# ----------------------
def test_iter_service_messages_paginates_and_applies_filter(monkeypatch, tmp_cfg_file: Path):
    cfg = GraphConfig.from_file(str(tmp_cfg_file))
    cli = GraphClient(cfg)

    # Bypass real auth
    monkeypatch.setattr(cli, "_acquire_token", lambda: "AT_FAKE")

    # Capture first call params to validate $filter & $top
    calls: List[Dict[str, Any]] = []

    def fake_get(url: str, params: Dict[str, str] | None) -> Dict[str, Any]:
        calls.append({"url": url, "params": params})
        if len(calls) == 1:
            # First page with nextLink
            return {
                "value": [{"id": "m1", "title": "A"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/messages?$skiptoken=abc",
            }
        else:
            # Last page
            return {"value": [{"id": "m2", "title": "B"}]}

    monkeypatch.setattr(cli, "_get", fake_get)

    since = dt.datetime(2024, 1, 1)  # naive -> should be treated as UTC Z
    items = list(cli.iter_service_messages(top=50, last_modified_ge=since))
    assert [m["id"] for m in items] == ["m1", "m2"]

    # Validate the first call carried expected params
    first = calls[0]["params"]
    assert first["$top"] == "50"
    assert first["$orderby"].startswith("lastModifiedDateTime")
    assert "lastModifiedDateTime ge" in first["$filter"]
    assert first["$filter"].endswith("Z")  # UTC Z suffix


# ----------------------
# Tests: error propagation when PKCS12 invalid
# ----------------------
def test_pkcs12_invalid_raises(monkeypatch, tmp_cfg_file: Path):
    # Make the loader raise (simulates wrong password or a CER without key)
    def fake_load_pkcs12(pfx_bytes: bytes, password: bytes | None):  # noqa: ANN001
        raise ValueError("Invalid password or PKCS12 data")

    monkeypatch.setenv("M365_PFX_PASSWORD", "anything")
    monkeypatch.setattr(gcmod, "load_key_and_certificates", fake_load_pkcs12)

    cfg = GraphConfig.from_file(str(tmp_cfg_file))
    cli = GraphClient(cfg)

    with pytest.raises(Exception) as ei:
        cli._acquire_token()
    assert "PKCS12" in str(ei.value) or "Invalid password" in str(ei.value)
