#!/usr/bin/env bash
set -e

IDS="$1"
PROMPT_FILE="$2"
OUTPUT_FILE="$3"

# Default model
if [ -z "$OPENAI_MODEL" ]; then
  OPENAI_MODEL="gpt-4o"
fi

# Default base URL if not set
if [ -z "$OPENAI_BASE_URL" ]; then
  OPENAI_BASE_URL="https://api.openai.com/v1"
fi

echo "Using model: $OPENAI_MODEL"
echo "Generating report for Roadmap IDs: $IDS"

# Function to call OpenAI API
call_openai_api() {
  MODEL_TO_USE="$1"

  curl -sS -X POST \
    -H "Authorization: Bearer ${OPENAI_API_KEY}" \
    -H "OpenAI-Organization: ${OPENAI_ORG_ID}" \
    -H "Content-Type: application/json" \
    "${OPENAI_BASE_URL}/chat/completions" \
    -d "{
      \"model\": \"${MODEL_TO_USE}\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"$(cat "$PROMPT_FILE")\"},
        {\"role\": \"user\", \"content\": \"Roadmap IDs: $IDS\"}
      ]
    }"
}

FALLBACK_USED="false"

# First attempt with the requested/default model
RESPONSE=$(call_openai_api "$OPENAI_MODEL")

# Check for "organization must be verified" or "model_not_found" error
if echo "$RESPONSE" | grep -q "organization must be verified\|model_not_found"; then
  echo "⚠️ $OPENAI_MODEL is not available for your org. Falling back to gpt-4o..."
  RESPONSE=$(call_openai_api "gpt-4o")
  FALLBACK_USED="true"
fi

# Save output
echo "$RESPONSE" > "$OUTPUT_FILE"

# Append fallback note to Markdown file if needed
if [ "$FALLBACK_USED" = "true" ]; then
  echo -e "\n---\n**Note:** This report was generated using *gpt-4o* due to lack of access to *$OPENAI_MODEL* in your organization." >> "$OUTPUT_FILE"
fi

echo "✅ Report saved to $OUTPUT_FILE"
