#!/usr/bin/env bash
set -euo pipefail

IN_MD="${1:-output/roadmap_report.md}"
OUT_CSV="${2:-output/roadmap_report.csv}"
OUT_JSON="${3:-output/roadmap_report.json}"
MONTHS="${4:-}"
SINCE="${5:-}"
UNTIL="${6:-}"
INCLUDE="${7:-}"
EXCLUDE="${8:-}"

# Locate parser
PARSER="parse_roadmap_markdown.py"
if [ ! -f "$PARSER" ]; then
  if [ -f "scripts/parse_roadmap_markdown.py" ]; then
    PARSER="scripts/parse_roadmap_markdown.py"
  else
    echo "Could not find parse_roadmap_markdown.py" >&2
    exit 1
  fi
fi

ARGS=(--in "$IN_MD" --csv "$OUT_CSV" --json "$OUT_JSON")
if [ -n "$MONTHS" ]; then
  ARGS+=(--months "$MONTHS")
fi
if [ -n "$SINCE" ]; then
  ARGS+=(--since "$SINCE")
  if [ -n "$UNTIL" ]; then
    ARGS+=(--until "$UNTIL")
  fi
fi
if [ -n "$INCLUDE" ]; then
  ARGS+=(--include-instances "$INCLUDE")
fi
if [ -n "$EXCLUDE" ]; then
  ARGS+=(--exclude-instances "$EXCLUDE")
fi

python "$PARSER" "${ARGS[@]}"
echo "Post-processing complete -> $OUT_CSV and $OUT_JSON"
