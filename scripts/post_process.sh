#!/usr/bin/env bash
set -e

INPUT_MD="$1"
OUTPUT_CSV="$2"
OUTPUT_JSON="$3"
MONTHS="$4"
SINCE="$5"
UNTIL="$6"
INCLUDE="$7"
EXCLUDE="$8"

echo "📄 Converting $INPUT_MD into CSV & JSON..."
python scripts/parse_roadmap_markdown.py "$INPUT_MD" "$OUTPUT_CSV" "$OUTPUT_JSON" "$MONTHS" "$SINCE" "$UNTIL" "$INCLUDE" "$EXCLUDE"
