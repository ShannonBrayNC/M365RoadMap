#!/usr/bin/env python3
"""
graph_client.py — Acquire Microsoft Graph token using a certificate (PFX)

Supports two certificate sources:
  1) File path  : config["pfx_path"]
  2) Inline b64 : config["pfx_base64"]  (Base64 string of the PFX)

Password is read from an env var (same as your PowerShell pattern):
  config["pfx_password_env"]  -> os.environ[that_name]

Required config keys:
  - tenant_id
  - client_id
  - graph_base (used by callers; not consumed here)
  - pfx_path OR pfx_base64
  - pfx_password_env (env var name that holds the PFX password)

Optional:
  - authority (defaults to "https://login.microsoftonline.com/<tenant_id>")
"""
from __future__ import annotations

import base64
import json
import os
import sys
from typing import Tuple, Optional

import msal
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.hazmat.primitives import serialization, hashes


def _load_pfx_bytes(pfx_bytes: bytes, password: Optional[str]) -> Tuple[str, str, str]:
    """Return (private_key_pem, public_cert_pem, thumbprint_hex) from a PFX blob."""
    key, cert, _chain = load_key_and_certificates(
        pfx_bytes, password.encode() if password else None
    )
    if key is None or cert is None:
        raise ValueError("PFX did not contain both a private key and a certificate.")

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    thumb_hex = cert.fingerprint(hashes.SHA1()).hex()  # AAD expects SHA-1 thumbprint

    return key_pem, cert_pem, thumb_hex


def _load_from_pfx_path(path: str, pwd_env_name: str) -> Tuple[str, str, str]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"PFX not found at {path}")
    pwd = os.environ.get(pwd_env_name, "")
    with open(path, "rb") as f:
        blob = f.read()
    return _load_pfx_bytes(blob, pwd)


def _load_from_pfx_b64(pfx_b64: str, pwd_env_name: str) -> Tuple[str, str, str]:
    if not pfx_b64 or not isinstance(pfx_b64, str):
        raise ValueError("pfx_base64 is empty or invalid.")
    pwd = os.environ.get(pwd_env_name, "")
    blob = base64.b64decode(pfx_b64)
    return _load_pfx_bytes(blob, pwd)


def acquire_token(config: dict) -> str:
    """Return an access token (string) for scope https://graph.microsoft.com/.default."""
    tenant_id = config.get("tenant_id")
    client_id = config.get("client_id")
    if not tenant_id or not client_id:
        raise ValueError("tenant_id and client_id are required in config.")

    authority = config.get("authority") or f"https://login.microsoftonline.com/{tenant_id}"

    # Prefer inline Base64 if present; fall back to file path
    if config.get("pfx_base64"):
        key_pem, cert_pem, thumb_hex = _load_from_pfx_b64(
            config["pfx_base64"], config.get("pfx_password_env", "")
        )
    elif config.get("pfx_path"):
        key_pem, cert_pem, thumb_hex = _load_from_pfx_path(
            config["pfx_path"], config.get("pfx_password_env", "")
        )
    else:
        raise ValueError("Provide either pfx_base64 or pfx_path in config.")

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential={
            "private_key": key_pem,
            "thumbprint": thumb_hex,
            "public_certificate": cert_pem,
        },
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Failed to acquire token: {result}")
    return result["access_token"]


if __name__ == "__main__":
    """
    Quick CLI test:
      python scripts/graph_client.py graph_config.json
    """
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "graph_config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    print(f"[graph_client] tenant={cfg.get('tenant_id')} client={cfg.get('client_id')}")
    print("[graph_client] Using credential source:",
          "pfx_base64" if cfg.get("pfx_base64") else "pfx_path" if cfg.get("pfx_path") else "NONE")

    token = acquire_token(cfg)
    print(f"[graph_client] token (first 40): {token[:40]}...")
