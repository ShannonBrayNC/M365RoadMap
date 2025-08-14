import sys
import json

if len(sys.argv) < 2:
    print("_No stats file produced._")
    sys.exit(0)

p = sys.argv[1]
try:
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    graph  = data.get("graph_rows", 0)
    public = data.get("public_rows", 0)
    rss    = data.get("rss_rows", 0)
    print("## Fetch Stats")
    print(f"- Graph rows: **{graph}**")
    print(f"- Public rows: **{public}**")
    print(f"- RSS rows: **{rss}**")
except FileNotFoundError:
    print("_No stats file produced._")