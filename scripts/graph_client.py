from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, cast

try:
    import requests  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]


def load_config(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return cast(dict[str, Any], data)


def get_pfx_password(cfg: dict[str, Any]) -> str:
    # prefer env override if PFX_PASSWORD_ENV is set
    env_var = cast(str, cfg.get("pfx_password_env", "")) or cast(
        str, cfg.get("PFX_PASSWORD_ENV", "")
    )
    if env_var:
        v = os.environ.get(env_var)
        if v:
            return v
    return cast(str, cfg.get("pfx_password", ""))


def authority_from_cfg(cfg: dict[str, Any]) -> str:
    return cast(str, cfg.get("authority", "https://login.microsoftonline.com"))


def build_headers(token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ----------------------------- Token & client --------------------------------


def acquire_token(cfg: dict[str, Any]) -> str:
    """
    Minimal placeholder for certificate-based client credentials.
    In your real implementation, you’d use MSAL w/ confidential client + cert.
    Here we just return a fake token string if the config looks sane.
    """
    tenant = cast(str, cfg.get("tenant") or cfg.get("TENANT") or "")
    client_id = cast(str, cfg.get("client_id") or cfg.get("CLIENT") or "")
    pfx_b64 = cast(str, cfg.get("pfx_base64") or cfg.get("PFX_B64") or "")
    pwd = get_pfx_password(cfg)

    if not (tenant and client_id and pfx_b64):
        raise RuntimeError("Missing tenant/client_id/pfx_base64 in config")

    # Validate PFX looks like base64; this does not load a cert (keeps this test-only)
    try:
        base64.b64decode(pfx_b64, validate=True)
    except Exception as exc:
        raise RuntimeError("Invalid PFX base64") from exc

    # Pretend we acquired a token
    return f"fake_token_for_{client_id}@{tenant}"


class GraphClient:
    def __init__(self, cfg: dict[str, Any], *, no_window: bool = False) -> None:
        self.cfg = cfg
        self.no_window = no_window
        self._token = None  # lazy

    @property
    def token(self) -> str:
        if not self._token:
            self._token = acquire_token(self.cfg)
        return self._token

    def fetch_messages(self) -> list[dict[str, Any]]:
        """
        Fetch admin messages (placeholder). Returns [] if network not available.
        """
        if requests is None:
            return []
        # You can customize the endpoint via config if desired
        base = self.cfg.get("graph_base", "https://graph.microsoft.com/beta")
        url = f"{base}/admin/serviceAnnouncement/messages"
        try:
            resp = requests.get(url, headers=build_headers(self.token), timeout=15)  # type: ignore[no-untyped-call]
            if resp.status_code >= 400:
                return []
            payload = resp.json()
            return cast(list[dict[str, Any]], payload.get("value", []))
        except Exception:
            return []
