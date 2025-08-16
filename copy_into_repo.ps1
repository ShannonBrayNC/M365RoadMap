
param(
  [string]$RepoRoot = "."
)
$ErrorActionPreference = "Stop"
Write-Host "Copying v2 files into $RepoRoot"

$files = @(
  "scripts\enrich\types.py",
  "scripts\enrich\merge_items.py",
  "scripts\cli\__init__.py",
  "scripts\cli\generate_report.py",
  "app\pages\1_📊_Roadmap.py",
  ".github\workflows\data.yml",
  "requirements.v2.additions.txt",
  "README_PATCH.md"
)

foreach ($rel in $files) {
  $src = Join-Path $PSScriptRoot $rel
  $dst = Join-Path $RepoRoot $rel
  $dstDir = Split-Path $dst -Parent
  if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Force -Path $dstDir | Out-Null }
  Copy-Item -Force $src $dst
  Write-Host "  + $rel"
}

Write-Host "Done. Next steps:"
Write-Host "  pip install -r requirements.v2.additions.txt"
Write-Host "  python -m scripts.cli.generate_report --mode auto"
Write-Host "  streamlit run app/streamlit_app.py"
