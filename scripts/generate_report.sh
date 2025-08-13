#!/usr/bin/env bash
set -euo pipefail

IDS_CSV="${1:-}"
SYSTEM_PROMPT_FILE="${2:-prompts/system_multi_id.md}"
OUT_MD="${3:-output/roadmap_report.md}"

if [ -z "${IDS_CSV}" ]; then
  echo "Usage: $0 \"498159,123456\" [system_prompt_file] [out.md]" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT_MD")"

SYSTEM_PROMPT=$(cat "$SYSTEM_PROMPT_FILE")
USER_PAYLOAD=$(jq -n --arg ids "$IDS_CSV" '{ids: ($ids | split(",")), product_context: "Enterprise tenant; heavy Teams usage; retention policies enforced; cross-tenant B2B enabled"}')

# Allow custom base URL (Azure OpenAI or self-hosted proxy) via OPENAI_BASE_URL
BASE_URL="${OPENAI_BASE_URL:-https://api.openai.com/v1}"

curl -sS "${BASE_URL}/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -d @- > /tmp/resp.json <<EOF
{
  "model": "${OPENAI_MODEL:-gpt-5}",
  "temperature": 0,
  "messages": [
    { "role": "system", "content": $(jq -Rs . <<< "$SYSTEM_PROMPT") },
    { "role": "user",   "content": $(jq -Rs . <<< "$USER_PAYLOAD") }
  ]
}
EOF

# Extract Markdown to file (compatible with both old & new response shapes)
CONTENT=$(jq -r '.choices[0].message.content // .choices[0].messages[0].content' /tmp/resp.json)
if [ -z "$CONTENT" ] || [ "$CONTENT" = "null" ]; then
  echo "No content returned from API. Full response:" >&2
  cat /tmp/resp.json >&2
  exit 1
fi

echo "$CONTENT" > "$OUT_MD"
echo "Report written to $OUT_MD"
