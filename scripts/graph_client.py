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


# --- replace this whole block in graph_client.py ---

from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

def _load_pfx_bytes(pfx_bytes: bytes, password: str | None):
    tried = []
    # 1) password from env (if supplied)
    if password:
      tried.append("env")
      try:
          key, cert, _chain = load_key_and_certificates(pfx_bytes, password.encode())
          return key, cert, _chain
      except Exception as e:
          last_env_err = e
    # 2) try empty password (some exports are unprotected)
    tried.append("empty")
    try:
        key, cert, _chain = load_key_and_certificates(pfx_bytes, None)
        return key, cert, _chain
    except Exception as e:
        last_empty_err = e

    # 3) try a raw empty string (rare format quirk)
    tried.append("blank")
    try:
        key, cert, _chain = load_key_and_certificates(pfx_bytes, b"")
        return key, cert, _chain
    except Exception as e:
        last_blank_err = e

    raise ValueError(f"PKCS12 load failed (tried {tried}). "
                     f"env_err={type(last_env_err).__name__ if password else 'n/a'}, "
                     f"empty_err={type(last_empty_err).__name__}, "
                     f"blank_err={type(last_blank_err).__name__}")

def _load_from_pfx_path(path: str, password_env: str | None):
    import os
    with open(path, "rb") as f:
        blob = f.read()
    pwd = os.environ.get(password_env) if password_env else None
    print(f"[graph_client] PFX bytes={len(blob)} password_set={bool(pwd)} (env={password_env})")
    return _load_pfx_bytes(blob, pwd)

def _load_from_pfx_b64(b64: str, password_env: str | None):
    import base64, os
    blob = base64.b64decode(b64)
    pwd = os.environ.get(password_env) if password_env else None
    print(f"[graph_client] PFX(b64) bytes={len(blob)} password_set={bool(pwd)} (env={password_env})")
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
