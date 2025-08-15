# Graph only (needs graph_config.json and $env:M365_PFX_PASSWORD)
$env:M365_PFX_PASSWORD = "secrets.M365_PFX_PASSWORD"
python .\scripts\selftest.py --months 1

# Skip Graph; test RSS on a couple of IDs
python .\scripts\selftest.py --no-graph --ids 498159,499430

# If you installed Playwright + browsers locally, include public scrape:
python -m pip install playwright
python -m playwright install chromium
python .\scripts\selftest.py --no-graph --ids 498159,499430
