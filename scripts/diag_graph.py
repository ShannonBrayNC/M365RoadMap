#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt
from scripts.graph_client import GraphConfig, GraphClient

def main() -> None:
    cfg = GraphConfig.from_env()
    cli = GraphClient(cfg)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365)
    n = 0
    for m in cli.iter_service_messages(top=10, last_modified_ge=since):
        print(m.get("id"), "-", m.get("title"))
        n += 1
    print("graph_messages:", n)

if __name__ == "__main__":
    main()
