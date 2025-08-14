#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys
from typing import Optional, Tuple
import msal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography import x509

SCOPE = ["https://graph.microsoft.com/.default"]

def _thumb_from_der(der: bytes) -> str:
    return hashlib.sha1(der).hexdigest().upper()

def _load_from_pfx(pfx_path: str, pwd_env: Optional[str]) -> Tuple[str, str]:
    if not os.path.isfile(pfx_path):
        raise FileNotFoundError(f"PFX not found at {pfx_path}")
    pwd_env_name = pwd_env or ""
    pwd_value = os.environ.get(pwd_env_name, "")
    print(f"[graph_client] PFX path: {pfx_path}", file=sys.stderr)
    print(f"[graph_client] PFX password env var: {pwd_env_name} (set={bool(pwd_value)})", file=sys.stderr)
    with open(pfx_path, "rb") as f:
        blob = f.read()
    key, cert, _ = load_key_and_certificates(blob, pwd_value.encode() if pwd_value else None)
    if not key or not cert:
        raise RuntimeError("Failed to load key/cert from PFX (bad password or file).")
    pem_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    ).decode()
    thumb = _thumb_from_der(cert.public_bytes(serialization.Encoding.DER))
    print(f"[graph_client] Cert thumbprint (derived): {thumb}", file=sys.stderr)
    return pem_key, thumb

def _load_from_pem(key_path: str, cert_path: Optional[str], thumb_fallback: Optional[str]) -> Tuple[str, str]:
    print(f"[graph_client] Using PEM key credential", file=sys.stderr)
    with open(key_path, "rb") as f:
        key_data = f.read()
    key = serialization.load_pem_private_key(key_data, password=None)
    pem_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    ).decode()
    if cert_path and os.path.isfile(cert_path):
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        thumb = _thumb_from_der(cert.public_bytes(serialization.Encoding.DER))
    else:
        if not thumb_fallback:
            raise RuntimeError("pem_cert_path missing and no CertificateThumbprint provided.")
        thumb = thumb_fallback.upper()
    print(f"[graph_client] PEM thumbprint: {thumb}", file=sys.stderr)
    return pem_key, thumb

def _try_export_from_store_with_powershell(thumbprint: str) -> Tuple[str, str]:
    if os.environ.get("ALLOW_POWERSHELL_EXPORT", "0") != "1":
        raise RuntimeError("PowerShell export disabled. Set ALLOW_POWERSHELL_EXPORT=1 to enable.")
    temp_pwd = os.environ.get("TEMP_PFX_PASSWORD")
    if not temp_pwd:
        raise RuntimeError("TEMP_PFX_PASSWORD env var not set for PowerShell export.")
    print("[graph_client] Using PowerShell export from cert store (thumbprint)", file=sys.stderr)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pfx_path = os.path.join(td, "exported.pfx")
        ps = rf'''
$ErrorActionPreference = "Stop"
$tp = "{thumbprint}"
$pwd = ConvertTo-SecureString -String "{temp_pwd}" -Force -AsPlainText
$cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object {{ $_.Thumbprint -eq $tp }}
if (-not $cert) {{ throw "Cert not found in CurrentUser\My: $tp" }}
Export-PfxCertificate -Cert $cert -FilePath "{pfx_path}" -Password $pwd | Out-Null
'''
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       check=True, capture_output=True, text=True)
        with open(pfx_path, "rb") as f:
            blob = f.read()
        key, cert, _ = load_key_and_certificates(blob, temp_pwd.encode())
        if not key or not cert:
            raise RuntimeError("Failed to load exported PFX.")
        pem_key = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()
        ).decode()
        thumb = _thumb_from_der(cert.public_bytes(serialization.Encoding.DER))
        print(f"[graph_client] Exported cert thumbprint: {thumb}", file=sys.stderr)
        return pem_key, thumb

def acquire_token(config: dict) -> str:
    print(f"[graph_client] tenant={config.get('tenant_id')} client={config.get('client_id')}", file=sys.stderr)
    if config.get("pfx_path"):
        print("[graph_client] Using PFX path credential", file=sys.stderr)
        pem_key, thumb = _load_from_pfx(config["pfx_path"], config.get("pfx_password_env"))
    elif config.get("pem_private_key_path"):
        pem_key, thumb = _load_from_pem(
            config["pem_private_key_path"],
            config.get("pem_cert_path"),
            config.get("CertificateThumbprint")
        )
    elif config.get("CertificateThumbprint"):
        pem_key, thumb = _try_export_from_store_with_powershell(config["CertificateThumbprint"])
    else:
        raise RuntimeError("No certificate source found. Provide pfx_path or pem_private_key_path or CertificateThumbprint + export allowed.")
    app = msal.ConfidentialClientApplication(
        client_id=config["client_id"],
        authority=config["authority"],
        client_credential={"private_key": pem_key, "thumbprint": thumb}
    )
    tok = msal.ConfidentialClientApplication.acquire_token_for_client(app, scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in tok:
        raise RuntimeError(f"Token acquisition failed: {tok}")
    return tok["access_token"]

if __name__ == "__main__":
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "graph_config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    token = acquire_token(cfg)
    print("Access token (truncated):", token[:48], "…")
