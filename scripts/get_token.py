import json
from graph_client import acquire_token

with open("graph_config.json", "rb") as f:
    cfg = json.load(f)

token = acquire_token(cfg)
print(token)
