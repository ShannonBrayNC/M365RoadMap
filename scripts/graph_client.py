# scripts/graph_client.py
# -*- coding: utf-8 -*-
"""
Graph client helper for app-only (client credentials) auth using a certificate.

Config JSON (graph_config.json) must provide:
- tenant_id (GUID)
- client_id (GUID)
- EITHER pfx_path OR pfx_base64
- pfx_password_env : name of env var that contains the PFX password (e.g., "M365_PFX_PASSWORD")
- graph_base : e.g. "https://graph.microsoft.com/v1.0"
OPTIONAL:
- authority : defaults to https://login.microsoftonline.com/{tenant_id}
- scope     : defaults to https://graph.microsoft.com/.default
"""

from __future__ import annotations

import os
import sys
import json
import base64
import hashlib
from typing import Tuple, Dict, Any, Optional

import requests
import msal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates


# ------------------------------
# PFX loading helpers
# ------------------------------

def _load_pfx_bytes(pfx_bytes: bytes, password: Optional[str]) -> Tuple[str, str, str]:
    """
    Load a PKCS#12 (PFX) blob and return (private_key_pem, certificate_pem, sha1_thumbprint).
    Password should be a plaintext string or None.
    """
    # Try password as provided; also try None/blank for unprotected PFX
    last_err = None
    for label, pwd in (("env", password.encode() if password else None),
                       ("empty", None),
                       ("blank", b"")):
        try:
            key, cert, _chain = load_key_and_certificates(pfx_bytes, pwd)
            if key is None or cert is None:
                raise ValueError("PFX did not contain both a private key and a certificate")
            # Convert to PEM text
            key_pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8")

            cert_pem = cert.public_bytes(
                encoding=serialization.Encoding.PEM
            ).decode("utf-8")

            # SHA1 thumbprint is over the DER-encoded certificate
            der = cert.public_bytes(serialization.Encoding.DER)
            thumb_hex = hashlib.sha1(der).hexdigest().upper()

            return key_pem, cert_pem, thumb_hex
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise ValueError(f"Failed to load PFX: {type(last_err).__name__}: {last_err}")  # type: ignore[misc]


def _load_from_pfx_path(path: str, password_env: Optional[str]) -> Tuple[str, str, str]:
    with open(path, "rb") as f:
        blob = f.read()
    pwd = os.environ.get(password_env) if password_env else None
    print(f"[graph_client] PFX(path='{path}') bytes={len(blob)} password_set={bool(pwd)} (env={password_env})")
    return _load_pfx_bytes(blob, pwd)


def _load_from_pfx_b64(pfx_b64: str, password_env: Optional[str]) -> Tuple[str, str, str]:
    blob = base64.b64decode(pfx_b64)
    pwd = os.environ.get(password_env) if password_env else None
    print(f"[graph_client] PFX(b64) bytes={len(blob)} password_set={bool(pwd)} (env={password_env})")
    return _load_pfx_bytes(blob, pwd)


# ------------------------------
# Token acquisition
# ------------------------------

def acquire_token(config: Dict[str, Any]) -> str:
    """
    Acquire an app-only access token for Microsoft Graph using cert-based client credentials.
    Returns the raw access token string.
    """
    tenant = config["tenant_id"]
    client = config["client_id"]
    authority = config.get("authority") or f"https://login.microsoftonline.com/{tenant}"
    scope = config.get("scope") or "https://graph.microsoft.com/.default"

    # Load cert creds (PEM strings + thumb)
    if "pfx_base64" in config:
        key_pem, cert_pem, thumb = _load_from_pfx_b64(config["pfx_base64"], config.get("pfx_password_env"))
        cred_source = "pfx_base64"
    elif "pfx_path" in config:
        key_pem, cert_pem, thumb = _load_from_pfx_path(config["pfx_path"], config.get("pfx_password_env"))
        cred_source = "pfx_path"
    else:
        raise RuntimeError("No PFX source in config (need pfx_base64 or pfx_path).")

    print(f"[graph_client] tenant={tenant} client={client}")
    print(f"[graph_client] authority={authority}")
    print(f"[graph_client] scope={scope}")
    print(f"[graph_client] thumbprint={thumb}")
    print(f"[graph_client] credential_source={cred_source}")

    app = msal.ConfidentialClientApplication(
        client_id=client,
        authority=authority,
        client_credential={
            # IMPORTANT: MSAL expects these exact keys and PEM **strings**
            "private_key": key_pem,
            "thumbprint": thumb,
            "public_certificate": cert_pem,
        },
    )

    result = app.acquire_token_silent(scopes=[scope], account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=[scope])

    if "access_token" in result:
        at = result["access_token"]
        print("[graph_client] token acquired, first 40 chars:", at[:40])
        return at

    # Show full MSAL error details
    print("[graph_client] FAILED to acquire token. Raw MSAL result:")
    try:
        print(json.dumps(result, indent=2))
    except Exception:
        print(result)
    err = result.get("error_description") or result.get("error") or "unknown_error"
    raise RuntimeError(f"MSAL error: {err}")


# ------------------------------
# Minimal Graph helpers
# ------------------------------

def get_graph_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def graph_get_json(url: str, token: str) -> Dict[str, Any]:
    s = get_graph_session(token)
    r = s.get(url, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Graph GET {url} failed: {r.status_code} {r.text}")
    return r.json()


def fetch_service_messages(config: Dict[str, Any], top: int = 100) -> Dict[str, Any]:
    """
    Quick fetch of the first page of serviceAnnouncement messages to verify permissions.
    Requires application permission: ServiceMessage.Read.All + admin consent.
    """
    base = config.get("graph_base", "https://graph.microsoft.com/v1.0").rstrip("/")
    token = acquire_token(config)
    url = f"{base}/admin/serviceAnnouncement/messages?$top={int(top)}"
    return graph_get_json(url, token)


# ------------------------------
# CLI entry point
# ------------------------------

def _load_config(path: str) -> Dict[str, Any]:
    with open(path, "rb") as f:
        return json.load(f)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print("Usage: python scripts/graph_client.py <graph_config.json> [--test-messages]")
        sys.exit(2)

    cfg_path = argv[1]
    test_msgs = ("--test-messages" in argv)

    cfg = _load_config(cfg_path)

    # Acquire token and optionally hit the messages endpoint
    token = acquire_token(cfg)

    if test_msgs:
        print("[graph_client] Testing serviceAnnouncement/messages ...")
        try:
            data = fetch_service_messages(cfg, top=5)
            print(json.dumps(data, indent=2))
        except Exception as e:  # noqa: BLE001
            print("[graph_client] Fetch failed:", e)
            raise
    else:
        # Print just the token (stdout), so callers can capture it:
        print(token)


if __name__ == "__main__":
    main(sys.argv)
