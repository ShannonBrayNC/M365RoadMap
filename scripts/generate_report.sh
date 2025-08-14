#!/usr/bin/env bash
set -euo pipefail

IDS_CSV="${1:?Usage: $0 <ids_comma_separated> <system_prompt_md> <out_md>}"
SYSTEM_PROMPT_PATH="${2:?Usage: $0 <ids_comma_separated> <system_prompt_md> <out_md>}"
OUT_MD="${3:-output/roadmap_report.md}"

: "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"
OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o}"
OPENAI_ORG_ID="${OPENAI_ORG_ID:-}"

mkdir -p "$(dirname "$OUT_MD")"
# ensure we never reuse a stale file
rm -f "$OUT_MD"

python - <<'PY' "$IDS_CSV" "$SYSTEM_PROMPT_PATH" "$OUT_MD" "$OPENAI_API_KEY" "$OPENAI_BASE_URL" "$OPENAI_MODEL" "$OPENAI_ORG_ID"
import json, os, sys, textwrap, urllib.request

ids_csv, sys_path, out_md, api_key, base_url, model, org_id = sys.argv[1:]

with open(sys_path, "r", encoding="utf-8") as f:
    system_prompt = f.read()

# Minimal user prompt: just the IDs
user_prompt = f"Feature IDs: {ids_csv.strip()}"

payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    "temperature": 0.2
}

req = urllib.request.Request(
    url=f"{base_url.rstrip('/')}/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        **({"OpenAI-Organization": org_id} if org_id else {})
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
except urllib.error.HTTPError as e:
    msg = e.read().decode("utf-8", errors="replace")
    print("API ERROR:", msg, file=sys.stderr)
    raise

content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
if not content:
    print("No content returned from API. Full response:", json.dumps(data, indent=2), file=sys.stderr)
    sys.exit(1)

with open(out_md, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)

print(f"✅ Report written to {out_md}")
PY

echo "✅ Done."
