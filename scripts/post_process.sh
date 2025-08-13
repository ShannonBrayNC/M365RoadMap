#!/usr/bin/env bash
set -e

MD_FILE="$1"
CSV_FILE="$2"
JSON_FILE="$3"
MONTHS="$4"
SINCE="$5"
UNTIL="$6"
INCLUDE="$7"
EXCLUDE="$8"

echo "📄 Converting $MD_FILE into CSV & JSON..."
echo "🗓 Filtering: Months=$MONTHS Since=$SINCE Until=$UNTIL"
echo "🌐 Include Instances: $INCLUDE"
echo "🚫 Exclude Instances: $EXCLUDE"

python scripts/parse_roadmap_markdown.py \
  --input "$MD_FILE" \
  --csv "$CSV_FILE" \
  --json "$JSON_FILE" \
  --months "$MONTHS" \
  --since "$SINCE" \
  --until "$UNTIL" \
  --include "$INCLUDE" \
  --exclude "$EXCLUDE"

echo "✅ Conversion complete"
