#!/usr/bin/env python3
"""
Graph Doctor: validates certificate creds and Microsoft Graph connectivity.

Usage:
  python graph_doctor.py --tenant TENANT_ID --client CLIENT_ID \
    --pfx-b64 <base64> --pfx-pass <password> \
    [--authority-base https://login.microsoftonline.com] \
    [--scope https://graph.microsoft.com/.default] \
    [--endpoint /v1.0/organization]

Notes:
- Prints certificate details (subject/issuer/validity/thumbprint).
- Acquires app-only token with MSAL confidential client (cert-based).
- Dumps token claims (roles/scopes) safely (no name collision with PyJWT).
- Calls the requested Graph endpoint and gives permission hints on 403.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization  # type: ignore
from cryptography.hazmat.primitives.serialization import pkcs12  # type: ignore
import msal  # type: ignore


def _b64pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def load_pfx_from_b64(pfx_b64: str, password: Optional[str]) -> Tuple[Any, x509.Certificate, list[x509.Certificate]]:
    """Decode and load a PKCS#12/PFX from base64."""
    try:
        blob = base64.b64decode(pfx_b64)
    except Exception as e:
        raise RuntimeError(f"PFX base64 decode failed: {e}") from e

    try:
        key, cert, chain = pkcs12.load_key_and_certificates(
            blob, password.encode() if password else None
        )
    except Exception as e:
        raise RuntimeError(f"PFX load failed: {e}") from e

    if cert is None or key is None:
        raise RuntimeError("PFX does not contain both cert and private key")

    return key, cert, chain or []


def cert_thumbprint_sha1(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA1()).hex()


def cert_to_pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")


def key_to_pem(key: Any) -> str:
    # Export PKCS#8 unencrypted private key
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


def print_cert_details(cert: x509.Certificate, has_key: bool, chain_len: int) -> None:
    try:
        not_before = cert.not_valid_before.replace(tzinfo=None).isoformat()
        not_after = cert.not_valid_after.replace(tzinfo=None).isoformat()
    except Exception:
        # cryptography deprecations: prefer *_utc when available
        nb = getattr(cert, "not_valid_before_utc", cert.not_valid_before)
        na = getattr(cert, "not_valid_after_utc", cert.not_valid_after)
        not_before = nb.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        not_after = na.astimezone(timezone.utc).replace(tzinfo=None).isoformat()

    print("Certificate details:")
    print(f"  Subject       : {cert.subject.rfc4514_string()}")
    print(f"  Issuer        : {cert.issuer.rfc4514_string()}")
    print(f"  Not Before    : {not_before}")
    print(f"  Not After     : {not_after}")
    print(f"  SHA1 Thumbprint: {cert_thumbprint_sha1(cert)}")
    print(f"  Private Key   : {bool(has_key)}")
    print(f"  Chain length  : {chain_len}")
    print()


def get_token_with_cert(
    tenant: str,
    client_id: str,
    authority_base: str,
    private_key_pem: str,
    certificate_pem: str,
    thumbprint_hex: str,
    scope: str,
) -> Dict[str, Any]:
    authority = authority_base.rstrip("/") + "/" + tenant
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential={
            "private_key": private_key_pem,
            "thumbprint": thumbprint_hex,
            "public_certificate": certificate_pem,
        },
    )
    result = app.acquire_token_for_client(scopes=[scope])
    if "access_token" not in result:
        raise RuntimeError(f"Token acquisition failed: {json.dumps(result, indent=2)}")
    return result


def dump_claims_safely(access_token: str) -> Dict[str, Any]:
    # Try PyJWT first (if present), else manual decode (no signature verify)
    try:
        import jwt as pyjwt  # type: ignore
        claims = pyjwt.decode(access_token, options={"verify_signature": False})
    except Exception:
        parts = access_token.split(".")
        if len(parts) < 2:
            raise RuntimeError("Access token is not a JWT")
        payload_b64 = parts[1]
        payload_json = base64.urlsafe_b64decode(_b64pad(payload_b64)).decode("utf-8")
        claims = json.loads(payload_json)
    return claims


def permission_hint_for_endpoint(endpoint: str) -> list[str]:
    ep = endpoint.strip().lower()
    hints: list[str] = []
    if ep.startswith("/v1.0/organization") or ep.startswith("/beta/organization"):
        hints.append("Organization.Read.All")
    if "serviceannouncement/messages" in ep:
        hints.append("ServiceMessage.Read.All")
    if "servicehealth/healthoverviews" in ep or "servicehealth/issues" in ep:
        hints.append("ServiceHealth.Read.All")
    # Add other endpoints as needed
    return hints


def call_graph(access_token: str, endpoint: str) -> requests.Response:
    base = "https://graph.microsoft.com"
    url = base.rstrip("/") + endpoint
    headers = {"Authorization": f"Bearer {access_token}"}
    return requests.get(url, headers=headers, timeout=30)


def main() -> None:
    p = argparse.ArgumentParser(description="Validate certificate and Graph connectivity")
    p.add_argument("--tenant", required=True)
    p.add_argument("--client", required=True)
    p.add_argument("--pfx-b64", required=True, help="Base64-encoded PFX/PKCS12")
    p.add_argument("--pfx-pass", default="", help="Password for the PFX (if any)")
    p.add_argument("--authority-base", default="https://login.microsoftonline.com")
    p.add_argument("--scope", default="https://graph.microsoft.com/.default")
    p.add_argument("--endpoint", default="/v1.0/organization")
    args = p.parse_args()

    # Load certificate (no secrets echoed)
    try:
        key, cert, chain = load_pfx_from_b64(args.pfx_b64, args.pfx_pass or None)
    except Exception as e:
        print(f"ERROR: PFX decode/validation failed: {e}")
        sys.exit(1)

    print_cert_details(cert, has_key=bool(key), chain_len=len(chain))

    # Acquire token
    print("Acquiring token with certificate credentials...")
    try:
        token_result = get_token_with_cert(
            tenant=args.tenant,
            client_id=args.client,
            authority_base=args.authority_base,
            private_key_pem=key_to_pem(key),
            certificate_pem=cert_to_pem(cert),
            thumbprint_hex=cert_thumbprint_sha1(cert),
            scope=args.scope,
        )
    except Exception as e:
        print(f"ERROR: Token acquisition failed: {e}")
        sys.exit(1)

    print("Token acquired OK.")

    # Dump claims safely
    try:
        claims = dump_claims_safely(token_result["access_token"])
        roles = claims.get("roles", [])
        scopes = claims.get("scp")  # delegated scope if present
        print("App roles in token:", roles)
        if scopes:
            print("Delegated scopes (scp) in token:", scopes)
    except Exception as e:
        print(f"WARN: Could not decode token claims: {e}")

    # Call Graph
    endpoint = args.endpoint if args.endpoint.startswith("/") else "/" + args.endpoint
    print(f"Calling Graph: https://graph.microsoft.com{endpoint}")
    try:
        resp = call_graph(token_result["access_token"], endpoint)
    except Exception as e:
        print(f"ERROR: Graph call failed to send: {e}")
        sys.exit(1)

    print(f"HTTP {resp.status_code}")
    if resp.ok:
        # Print a small, pretty snippet to confirm success
        try:
            data = resp.json()
            snippet = json.dumps(data, indent=2)[:2000]
            print("Response JSON (truncated):")
            print(snippet)
        except Exception:
            print("Response body (truncated):")
            print(resp.text[:2000])
        sys.exit(0)

    # Handle common errors
    body = resp.text
    print("ERROR: Graph call failed. Body:")
    print(body[:4000])

    if resp.status_code == 403:
        hints = permission_hint_for_endpoint(endpoint)
        if hints:
            print("Permission hint(s) for this endpoint (Application permissions):")
            for h in hints:
                print(f"  - {h}")
            print("Make sure these are added in Azure AD App → API permissions → Microsoft Graph → Application permissions, and admin consent is granted.")

    sys.exit(1)


if __name__ == "__main__":
    main()
