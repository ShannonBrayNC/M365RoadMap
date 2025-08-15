import os, json, base64, sys, traceback
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

try:
    cfg = json.load(open("graph_config.json","r",encoding="utf-8"))
    pwd_name = cfg.get("pfx_password_env","M365_PFX_PASSWORD")
    pwd = os.environ.get(pwd_name, "")
    if not cfg.get("pfx_base64"):
        raise RuntimeError("graph_config.json.pfx_base64 is empty")
    blob = base64.b64decode(cfg["pfx_base64"])
    key, cert, chain = load_key_and_certificates(blob, pwd.encode() if pwd else None)
    print("OK:",
          cert.subject.rfc4514_string(),
          "key:", key is not None,
          "chain:", len(chain or []))
except Exception as e:
    print("ERROR:", e)
    traceback.print_exc()
    sys.exit(1)