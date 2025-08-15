import os, sys
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

PWD_ENV = "M365_PFX_PASSWORD"
pwd = os.environ.get(PWD_ENV, "")
print("env var name:", PWD_ENV)
print("env var bytes:", list(pwd.encode()))
data = open("_cfg.pfx","rb").read()
print("pfx bytes:", len(data))
try:
    key, cert, chain = load_key_and_certificates(data, pwd.encode())
    print("SUCCESS: cert subject:", cert.subject.rfc4514_string())
    print("Has private key:", key is not None)
except Exception as e:
    print("FAIL:", repr(e))
