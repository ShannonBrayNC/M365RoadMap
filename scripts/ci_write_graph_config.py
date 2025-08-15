#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

def main() -> None:
    tenant = os.environ.get("TENANT") or os.environ.get("GRAPH_TENANT_ID") or ""
    client = os.environ.get("CLIENT") or os.environ.get("GRAPH_CLIENT_ID") or ""
    pfx_b64 = os.environ.get("PFX_B64") or os.environ.get("M365_PFX_BASE64") or ""
    pfx_pwd_env = os.environ.get("PFX_PASSWORD_ENV", "M365_PFX_PASSWORD")

    cfg_path = Path("graph_config.json")
    if tenant and client and pfx_b64:
        cfg = {
            "tenant_id": tenant,
            "client_id": client,
            "pfx_base64": pfx_b64,
            "pfx_password_env": pfx_pwd_env,
            "graph_base": "https://graph.microsoft.com/v1.0",
            "authority_base": "https://login.microsoftonline.com",
        }
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        print("graph_config.json written.")
        return

    if cfg_path.exists():
        print("Using existing graph_config.json")
        return

    print("No Graph config available; set TENANT, CLIENT and PFX_B64 secrets.", file=sys.stderr)
    # still succeed; fetch will cope if --no-graph is set

if __name__ == "__main__":
    main()
