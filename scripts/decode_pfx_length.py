#!/usr/bin/env python3
import json
import base64
import sys
from pathlib import Path

if len(sys.argv) != 2:
    print(f"Usage: {Path(sys.argv[0]).name} <graph_config.json>", file=sys.stderr)
    sys.exit(1)

cfg_path = Path(sys.argv[1])
if not cfg_path.exists():
    print(f"❌ File not found: {cfg_path}", file=sys.stderr)
    sys.exit(1)

with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

pfx_b64 = cfg.get("pfx_base64", "")
if not pfx_b64:
    print("❌ No pfx_base64 found in config", file=sys.stderr)
    sys.exit(1)

try:
    raw = base64.b64decode(pfx_b64, validate=True)
except Exception as e:
    print(f"❌ Invalid Base64: {e}", file=sys.stderr)
    sys.exit(1)

print(f"PFX_B64 length: {len(pfx_b64)}")
print(f"Decoded PFX bytes: {len(raw)}")
