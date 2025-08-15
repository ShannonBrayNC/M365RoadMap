from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def main(path: str) -> None:
    p = Path(path)
    cfg: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    keys = ["tenant", "client_id", "pfx_base64", "pfx_password_env", "authority"]
    for k in keys:
        v = cfg.get(k)
        masked = "<set>" if v else "<empty>"
        if k == "pfx_base64" and v:
            masked = f"len={len(str(v))}"
        print(f"{k}: {masked}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: diag_graph.py <graph_config.json>")
        raise SystemExit(2)
    main(sys.argv[1])
