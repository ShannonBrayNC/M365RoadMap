param(
  [string]$ConfigPath = "graph_config.json"
)

if (-not (Test-Path $ConfigPath)) { throw "Can't find $ConfigPath" }

$py = @"
import os, json, base64, sys, traceback
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

cfg_path = r"$ConfigPath"
try:
    cfg = json.load(open(cfg_path, "r", encoding="utf-8"))
    pwd_name = cfg.get("pfx_password_env","M365_PFX_PASSWORD")
    pwd = os.environ.get(pwd_name, "")
    if not cfg.get("pfx_base64"):
        raise RuntimeError(f"{cfg_path}.pfx_base64 is empty")
    blob = base64.b64decode(cfg["pfx_base64"])
    key, cert, chain = load_key_and_certificates(blob, pwd.encode() if pwd else None)
    print("OK:",
          cert.subject.rfc4514_string(),
          "sha1:", cert.fingerprint(__import__("cryptography").hazmat.primitives.hashes.SHA1()).hex(),
          "key:", key is not None,
          "chain:", len(chain or []))
except Exception as e:
    print("ERROR:", e)
    traceback.print_exc()
    sys.exit(1)
"@

# Prefer venv python if available
$pyExe = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
$py | & $pyExe -
