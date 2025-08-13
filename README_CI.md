# Roadmap CI: Generate Markdown + Filtered CSV/JSON

This CI setup:
1) **Generates a multi-ID Microsoft 365 Roadmap report** (Markdown) using your LLM of choice (default `gpt-5`).
2) **Post-processes** the report to extract the **Master Summary Table**, producing **CSV** and **JSON**.
3) Supports **date window filters (≤ 6 months)** and **Cloud Instance filters** (DoD, GCC, GCC High, Worldwide).

## Files
- `.github/workflows/roadmap-report.yml` — the GitHub Actions workflow.
- `scripts/generate_report.sh` — calls the Chat Completions API to produce Markdown.
- `scripts/post_process.sh` — runs the parser with filters to create CSV/JSON.
- `prompts/system_multi_id.md` — the system prompt used for report generation.

> Ensure `parse_roadmap_markdown.py` is committed at repo root or under `scripts/`.

## Required secrets
- `OPENAI_API_KEY` — your API key (do **not** commit keys!)
- Optional:
  - `OPENAI_BASE_URL` — use a custom base (e.g., Azure OpenAI, proxy). Default is `https://api.openai.com/v1`.

## Running on demand
In GitHub → **Actions** → **Build Microsoft 365 Roadmap Report** → **Run workflow**, supply:
- `ids`: e.g. `498159,123456,987654`
- `months`: `1..6` (optional)
- or `since` + `until` (optional; if `until` omitted, window defaults to 6 months after `since`)
- `include_instances`: `DoD,GCC,GCC High,Worldwide (Standard Multi-Tenant)` (optional)
- `exclude_instances`: same format (optional)
- `model`: default `gpt-5`
- `report_title`: filename prefix

Artifacts will be attached automatically; the workflow also attempts a commit back to `output/` on manual runs.

## Expected report shape
Ask the model to include a single **Master Summary Table** with the columns:
```
| ID | Title | Product/Workload | Status | Release phase | Targeted dates | Cloud instance | Short description | Official Roadmap link |
```

## Local quick start
```bash
# Generate report locally (requires jq and curl)
OPENAI_API_KEY=... scripts/generate_report.sh "498159,123456"
# Post-process with last 6 months + instance include
python parse_roadmap_markdown.py --in output/roadmap_report.md \
  --months 6 \
  --include-instances "Worldwide (Standard Multi-Tenant),GCC High" \
  --csv output/roadmap_report.csv --json output/roadmap_report.json
```

## Notes
- Parser skips rows with unparseable dates when a date filter is active.
- Instance filtering normalizes common variants (e.g., `Worldwide` → `Worldwide (Standard Multi-Tenant)`).
- Keep your API keys in **repository secrets** to avoid push-protection failures.
