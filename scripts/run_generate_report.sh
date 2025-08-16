#!/usr/bin/env bash
set -Eeuo pipefail

: "${TITLE:?TITLE env var must be set}"

IN_CSV="output/${TITLE}_master.csv"
OUT_MD="output/${TITLE}.md"

ARGS=( --title "$TITLE" --master "$IN_CSV" --out "$OUT_MD" )

if [[ -n "${SINCE:-}"  ]]; then ARGS+=( --since  "$SINCE" );  fi
if [[ -n "${MONTHS:-}" ]]; then ARGS+=( --months "$MONTHS" ); fi

if [[ "${CLOUD_GENERAL,,}" == "true" ]]; then ARGS+=( --cloud "Worldwide (Standard Multi-Tenant)" ); fi
if [[ "${CLOUD_GCC,,}"     == "true" ]]; then ARGS+=( --cloud "GCC" ); fi
if [[ "${CLOUD_GCCH,,}"    == "true" ]]; then ARGS+=( --cloud "GCC High" ); fi
if [[ "${CLOUD_DOD,,}"     == "true" ]]; then ARGS+=( --cloud "DoD" ); fi

if [[ -n "${PRODUCTS:-}"   ]]; then ARGS+=( --products   "$PRODUCTS" );   fi
if [[ -n "${PUBLIC_IDS:-}" ]]; then ARGS+=( --forced-ids "$PUBLIC_IDS" ); fi

python scripts/generate_report.py "${ARGS[@]}"

echo "md=${OUT_MD}" >> "$GITHUB_OUTPUT"