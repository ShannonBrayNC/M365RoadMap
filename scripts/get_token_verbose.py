#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
from typing import Any, Dict

import msal
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import (
    load_key_and_certificates,
)


def _die(msg: str, rc: int = 1) -> None:
    print(f"[get_token_verbose] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(rc)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Verbose MSAL client-credential token fetch using graph_config.json"
    )
    ap.add_argument(
        "--config", required=True, help="Path to graph_config.json (with pfx_base64)"
    )
    args = ap.parse_args()

    # Load config
    try:
        cfg: Dict[str, Any] = json.load(open(args.config, "r", encoding="utf-8"))
    except Exception as e:
        _die(f"Failed to read config '{args.config}': {e}")

    tenant = cfg.get("tenant_id") or ""
    client = cfg.get("client_id") or ""
    pfx_b64 = cfg.get("pfx_base64") or ""
    pwd_env = cfg.get("pfx_password_env", "M365_PFX_PASSWORD")
    graph_base = cfg.get("graph_base", "https://graph.microsoft.com/v1.0")
    authority_base = cfg.get("authority_base", "https://login.microsoftonline.com")

    if not tenant or not client or not pfx_b64:
        _die("Config missing tenant_id/client_id/pfx_base64")

    pwd = os.environ.get(pwd_env)
    if not pwd:
        _die(
            f"Environment variable '{pwd_env}' is empty. "
            f"Set it to your PFX password before running."
        )

    # Decode and inspect PFX
    try:
        blob = base64.b64decode(pfx_b64)
        key, cert, chain = load_key_and_certificates(blob, pwd.encode())
    except Exception as e:
        _die(f"PKCS#12 load failed: {e}")

    if not key or not cert:
        _die("PFX did not contain a private key and certificate")

    thumb = cert.fingerprint(hashes.SHA1()).hex()  # MSAL requires SHA-1 thumbprint
    subj = cert.subject.rfc4514_string()

    print("== PFX / Certificate ==")
    print(f" Subject        : {subj}")
    print(f" Thumbprint(SHA1): {thumb}")
    print(f" NotBefore      : {cert.not_valid_before_utc}")
    print(f" NotAfter       : {cert.not_valid_after_utc}")
    print(f" HasPrivateKey  : {'yes' if key else 'no'}")
    print(f" ChainLen       : {len(chain) if chain else 0}")
    print()

    # Build MSAL app
    authority = f"{authority_base.rstrip('/')}/{tenant}"
    resource = graph_base.split("/v1.0")[0].rstrip("/")
    scope = f"{resource}/.default"

    pem_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    print("== MSAL Request ==")
    print(f" Authority  : {authority}")
    print(f" ClientId   : {client}")
    print(f" Scope      : {scope}")
    print(f" Time (UTC) : {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        app = msal.ConfidentialClientApplication(
            client_id=client,
            authority=authority,
            client_credential={"private_key": pem_key, "thumbprint": thumb},
        )
    except Exception as e:
        _die(f"MSAL app creation failed: {e}")

    # Acquire token
    result = app.acquire_token_for_client(scopes=[scope])

    print("== MSAL Response ==")
    if "access_token" in result:
        token = result["access_token"]
        masked = token[:32] + "..." + token[-16:]
        print(" Success: yes")
        print(f" TokenType : {result.get('token_type', 'Bearer')}")
        print(f" ExpiresIn : {result.get('expires_in')}")
        print(f" ExtExpIn  : {result.get('ext_expires_in')}")
        print(f" AccessTok : {masked}")
        print(" Tip       : Set LOG_LEVEL=INFO to see MSAL cache logs.")
        sys.exit(0)
    else:
        print(" Success: no")
        print(f" Error    : {result.get('error')}")
        print(f" Desc     : {result.get('error_description')}")
        print(f" CorrelId : {result.get('correlation_id')}")
        _die("Token acquisition failed", rc=2)


if __name__ == "__main__":
    main()
