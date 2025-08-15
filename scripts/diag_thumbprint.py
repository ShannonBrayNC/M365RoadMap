# scripts/diag_thumbprint.py
import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

cfg = json.load(open("graph_config.json", "rb"))

# Load PFX bytes from base64 or path
if "pfx_base64" in cfg:
    blob = base64.b64decode(cfg["pfx_base64"])
elif "pfx_path" in cfg:
    with open(cfg["pfx_path"], "rb") as f:
        blob = f.read()
else:
    raise SystemExit("No pfx_base64 or pfx_path in graph_config.json")

pwd = os.environ.get(cfg.get("pfx_password_env", ""))
key, cert, chain = load_key_and_certificates(blob, pwd.encode() if pwd else None)
if cert is None:
    raise SystemExit("Loaded PFX but no certificate found")

# Compute SHA1 thumbprint over DER-encoded certificate
der = cert.public_bytes(serialization.Encoding.DER)
sha1 = hashlib.sha1(der).hexdigest().upper()

print("PFX certificate subject: ", cert.subject.rfc4514_string())
print("PFX certificate issuer : ", cert.issuer.rfc4514_string())
print("PFX thumbprint (SHA1)  :", sha1)
