#!/usr/bin/env python3
from __future__ import annotations

import base64
import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Dict, Generator, Optional

import msal
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

DEFAULT_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_AUTHORITY = "https://login.microsoftonline.com"


@dataclass
class GraphConfig:
    tenant_id: str
    client_id: str
    pfx_base64: str
    pfx_password_env: str
    graph_base: str = DEFAULT_GRAPH_BASE
    authority_base: str = DEFAULT_AUTHORITY

    @staticmethod
    def from_file(path: str) -> "GraphConfig":
        data = json.load(open(path, "r", encoding="utf-8"))
        return GraphConfig(
            tenant_id=data["tenant_id"],
            client_id=data["client_id"],
            pfx_base64=data["pfx_base64"],
            pfx_password_env=data.get("pfx_password_env", "M365_PFX_PASSWORD"),
            graph_base=data.get("graph_base", DEFAULT_GRAPH_BASE),
            authority_base=data.get("authority_base", DEFAULT_AUTHORITY),
        )

    @staticmethod
    def from_env() -> "GraphConfig":
        # Support both GRAPH_* and short env names used in the workflow
        tenant = os.environ.get("GRAPH_TENANT_ID") or os.environ.get("TENANT")
        client = os.environ.get("GRAPH_CLIENT_ID") or os.environ.get("CLIENT")
        pfx_b64 = os.environ.get("M365_PFX_BASE64") or os.environ.get("PFX_B64")
        if not (tenant and client and pfx_b64):
            raise RuntimeError("Missing GRAPH_TENANT_ID/TENANT, GRAPH_CLIENT_ID/CLIENT, or M365_PFX_BASE64/PFX_B64")
        return GraphConfig(
            tenant_id=tenant,
            client_id=client,
            pfx_base64=pfx_b64,
            pfx_password_env=os.environ.get("PFX_PASSWORD_ENV", "M365_PFX_PASSWORD"),
            graph_base=os.environ.get("GRAPH_BASE", DEFAULT_GRAPH_BASE),
            authority_base=os.environ.get("AUTHORITY_BASE", DEFAULT_AUTHORITY),
        )


class GraphClient:
    def __init__(self, cfg: GraphConfig) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self._app: Optional[msal.ConfidentialClientApplication] = None
        self._token: Optional[Dict] = None
        self._token_acquired_at: Optional[float] = None

    # ----- Auth -----
    def _build_app(self) -> msal.ConfidentialClientApplication:
        if self._app:
            return self._app

        pfx_bytes = base64.b64decode(self.cfg.pfx_base64)
        password = os.environ.get(self.cfg.pfx_password_env)
        private_key, cert, _ = load_key_and_certificates(
            pfx_bytes, password.encode() if password else None
        )
        if private_key is None or cert is None:
            raise RuntimeError("Invalid PFX: private key or certificate missing")

        pem_key = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        # MSAL requires the SHA-1 thumbprint for cert creds
        thumb = cert.fingerprint(hashes.SHA1()).hex()  # nosec B303 (required by MSAL)

        authority = f"{self.cfg.authority_base.rstrip('/')}/{self.cfg.tenant_id}"
        self._app = msal.ConfidentialClientApplication(
            client_id=self.cfg.client_id,
            authority=authority,
            client_credential={"private_key": pem_key, "thumbprint": thumb},
        )
        return self._app

    def _acquire_token(self) -> str:
        # Reuse cached token if valid for another 2 minutes
        if self._token and self._token_acquired_at:
            import time
            remaining = (self._token_acquired_at + int(self._token.get("expires_in", 0))) - time.time()
            if remaining > 120:
                return self._token["access_token"]

        app = self._build_app()
        # Build resource from configured graph_base (e.g., https://graph.microsoft.com)
        resource = self.cfg.graph_base.split("/v1.0")[0].rstrip("/")
        result = app.acquire_token_for_client(scopes=[f"{resource}/.default"])
        if "access_token" not in result:
            raise RuntimeError(f"MSAL token acquisition failed: {result.get('error_description') or result}")
        self._token = result

        import time
        self._token_acquired_at = time.time()
        return result["access_token"]

    # ----- GET with bearer -----
    def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        token = self._acquire_token()
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.session.get(url, headers=headers, params=params, timeout=(10, 60))
        resp.raise_for_status()
        return resp.json()

    # ----- Public API -----
    def iter_service_messages(
        self,
        top: int = 100,
        include_drafts: bool = True,  # reserved for future filter
        last_modified_ge: Optional[dt.datetime] = None,
    ) -> Generator[Dict, None, None]:
        """
        Yields objects from /admin/serviceAnnouncement/messages
        """
        url = f"{self.cfg.graph_base.rstrip('/')}/admin/serviceAnnouncement/messages"
        params: Dict[str, str] = {"$top": str(min(max(top, 1), 100))}
        params["$orderby"] = "lastModifiedDateTime desc"

        # $filter
        filters = []
        if last_modified_ge is not None:
            if last_modified_ge.tzinfo is None:
                last_modified_ge = last_modified_ge.replace(tzinfo=dt.timezone.utc)
            iso = last_modified_ge.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
            filters.append(f"lastModifiedDateTime ge {iso}")
        if filters:
            params["$filter"] = " and ".join(filters)

        while True:
            data = self._get(url, params=params)
            for item in data.get("value", []):
                yield item
            next_link = data.get("@odata.nextLink")
            if not next_link:
                break
            url = next_link
            params = None  # nextLink already has query
