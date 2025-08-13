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

echo "📄 Converting $IN_MD into CSV & JSON..."
echo "🗓 months=$MONTHS since=$SINCE until=$UNTIL"
echo "🌐 include=$INCLUDE exclude=$EXCLUDE"

PY="scripts/parse_roadmap_markdown.py"
if [ ! -f "$PY" ]; then
  echo "❌ $PY not found"; exit 1
fi

# Debug: show exact python command
set -x
python "$PY" \
  --input "$IN_MD" \
  --csv "$OUT_CSV" \
  --json "$OUT_JSON" \
  --months "$MONTHS" \
  --since "$SINCE" \
  --until "$UNTIL" \
  --include "$INCLUDE" \
  --exclude "$EXCLUDE"
set +x

echo "✅ Conversion complete → $OUT_CSV and $OUT_JSON"
