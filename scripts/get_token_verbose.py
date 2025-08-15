from __future__ import annotations

import argparse
import platform

from scripts.graph_client import acquire_token, load_config


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, help="Path to graph_config.json")
    args = p.parse_args(argv)

    print(platform.python_version())
    cfg = load_config(args.config)
    try:
        tok = acquire_token(cfg)
        print(f"OK token len={len(tok)}")
    except Exception as exc:
        print(f"ERROR acquiring token: {exc}")


if __name__ == "__main__":
    main()
