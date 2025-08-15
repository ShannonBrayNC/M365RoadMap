<#
.SYNOPSIS
  Hardens the repo:
    - Writes .gitignore, pyproject.toml, and a hardened .pre-commit-config.yaml
    - Removes sensitive files and creates example templates
    - Installs pre-commit + detect-secrets (via Python) and creates a baseline
    - Adds output/.gitkeep
    - (Optional) Rewrites Git history to purge sensitive files

.PARAMETER RewriteHistory
  If set, attempts to use git-filter-repo to remove sensitive files from history.

.PARAMETER Force
  Overwrite existing config files without prompting.

.EXAMPLE
  pwsh scripts/hardening.ps1 -RewriteHistory -Force
#>

param(
  [switch]$RewriteHistory,
  [switch]$Force
)


[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'


Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve repo root = parent of this script directory
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Write-FileSafe {
  param([string]$Path, [string]$Content, [switch]$Overwrite)
  if ((Test-Path $Path) -and -not $Overwrite) {
    Write-Host "Skipping $Path (exists). Use -Force to overwrite." -ForegroundColor Yellow
    return
  }
  $dir = Split-Path $Path -Parent
  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $Content | Out-File -FilePath $Path -Encoding utf8 -Force
  Write-Host "Wrote $Path" -ForegroundColor Green
}

function Get-Python {
  try { & python --version *>$null; return "python" } catch {}
  try { & py -3 --version *>$null; return "py -3" } catch {}
  throw "Python not found in PATH"
}

# Use pip show (works even if stdlib 'importlib' is shadowed)
function Ensure-PythonModule {
  param([string]$Package)  # e.g., 'pre-commit' or 'detect-secrets'
  $py = Get-Python
  & $py -m pip show $Package *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing $Package ..." -ForegroundColor Cyan
    & $py -m pip install $Package --quiet
    if ($LASTEXITCODE -ne 0) { throw "Failed to install Python package: $Package" }
  }
}


# ---------- .gitignore ----------
$gitignore = @'
__pycache__/
*.py[cod]
*.so
*.egg-info/
.venv/
venv/
env/
dist/
build/
.coverage
coverage.xml
htmlcov/
.pytest_cache/
.ipynb_checkpoints/
*.log
*.tmp
.DS_Store
Thumbs.db
.vscode/
.idea/
*.code-workspace

# Project
/output/*
!/output/.gitkeep
.env
.env.*
secrets.*
*.pfx
*.p12
*.pem
*.cer
*.key
*pfx.b64

graph_config.json
graph_config.inline.json
!graph_config.example.json
!graph_config.inline.example.json

scripts/*.bak
prompts/*.bak
'@
Write-FileSafe -Path ".gitignore" -Content $gitignore -Overwrite:$Force

# ---------- pyproject.toml (tooling only) ----------
$pyproject = @'
[tool.ruff]
line-length = 100
target-version = "py311"
lint.select = ["E","W","F","I","UP","N","B","A","C4","PT","SIM","ARG","T20","ERA","DTZ"]
lint.ignore = ["E203"]
lint.exclude = ["output"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
docstring-code-format = true

[tool.mypy]
python_version = "3.11"
warn_unused_configs = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_return_any = true
disallow_untyped_defs = true
no_implicit_optional = true
check_untyped_defs = true
exclude = ["output/"]

[tool.pytest.ini_options]
minversion = "7.0"
addopts = "-q"
testpaths = ["tests"]

[tool.coverage.run]
branch = true
source = ["."]
omit = ["*/tests/*", "output/*"]

[tool.bandit]
skips = ["B101"]
'@
Write-FileSafe -Path "pyproject.toml" -Content $pyproject -Overwrite:$Force

# ---------- .pre-commit-config.yaml ----------
# (fixed: mdformat plugins must be in additional_dependencies; removed invalid hook IDs)
$precommit = @'
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-yaml
      - id: check-json
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: mixed-line-ending
      - id: check-merge-conflict

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.7
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ["--baseline", ".secrets.baseline"]
        exclude: |
          (?x)(
            ^output/|
            ^prompts/
          )

  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.9
    hooks:
      - id: bandit
        args: ["-q", "-r", "."]

  - repo: https://github.com/executablebooks/mdformat
    rev: 0.7.17
    hooks:
      - id: mdformat
        additional_dependencies:
          - mdformat-frontmatter
          - mdformat-gfm

  - repo: local
    hooks:
      - id: block-certs-and-keys
        name: Block certificate/private key files
        entry: bash -c 'echo "Refusing to commit certificate/private key-like files."; exit 1'
        language: system
        files: >
          (?x)^(
            .*\.pfx$|
            .*\.p12$|
            .*\.pem$|
            .*\.cer$|
            .*\.key$|
            .*pfx\.b64$
          )

      - id: block-real-configs
        name: Block committing real graph_config files
        entry: bash -c 'echo "Commit .example.json instead of real graph_config.*.json"; exit 1'
        language: system
        files: ^graph_config(\.inline)?\.json$

      - id: block-output-artifacts
        name: Block output artifacts
        entry: bash -c 'echo "Do not commit files under /output"; exit 1'
        language: system
        files: ^output/.+
'@
Write-FileSafe -Path ".pre-commit-config.yaml" -Content $precommit -Overwrite:$Force

# ---------- Create output/.gitkeep ----------
if (-not (Test-Path "output")) { New-Item -ItemType Directory -Path "output" | Out-Null }
if (-not (Test-Path "output/.gitkeep")) { New-Item -ItemType File -Path "output/.gitkeep" | Out-Null }

# ---------- Remove sensitive files (working tree) ----------
$sensitive = @("pfx.b64","graph_config.json","graph_config.inline.json","Export-PrivateKey.ps1")
foreach ($f in $sensitive) {
  if (Test-Path $f) {
    Remove-Item -Force $f
    Write-Host "Removed $f from working tree." -ForegroundColor Yellow
  }
}

# ---------- Add example config (placeholders only; DO NOT commit real IDs/secrets) ----------
$exampleCfg = @'
{
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "client_id": "00000000-0000-0000-0000-000000000000",
  "pfx_base64": "REPLACE_WITH_BASE64_PFX",
  "pfx_password_env": "",
  "graph_base": "https://graph.microsoft.com/v1.0",
  "authority_base": "https://login.microsoftonline.com"
}
'@
Write-FileSafe -Path "graph_config.example.json" -Content $exampleCfg -Overwrite:$Force

# ---------- Ensure Python tools ----------
$py = Get-Python
& $py --version | Write-Host
& $py -m pip --version | Write-Host

Ensure-PythonModule -Package "pre-commit"
Ensure-PythonModule -Package "detect-secrets"


# ---------- Pre-commit install & secrets baseline ----------
Write-Host "Installing git hooks (pre-commit, forcing new style)..." -ForegroundColor Cyan
& $py -m pre_commit install -f


if (-not (Test-Path ".secrets.baseline")) {
  Write-Host "Creating detect-secrets baseline..." -ForegroundColor Cyan
  & $py -m detect_secrets scan | Out-File -Encoding utf8 ".secrets.baseline"
} else {
  Write-Host ".secrets.baseline already exists; skipping." -ForegroundColor Yellow
}

Write-Host "Running pre-commit on all files (first run may take a while)..." -ForegroundColor Cyan
# Don't fail the script if hooks fix things on first run
& $py -m pre_commit run --all-files; $null = $LASTEXITCODE

# ---------- Optional: rewrite history to purge secrets ----------
if ($RewriteHistory) {
  Write-Host "Attempting history rewrite with git-filter-repo..." -ForegroundColor Magenta
  $hasFilterRepo = $true
  try { git filter-repo -h | Out-Null } catch { $hasFilterRepo = $false }
  if (-not $hasFilterRepo) {
    try {
      & $py -m pip install git-filter-repo --quiet
      git filter-repo -h | Out-Null
      $hasFilterRepo = $true
    } catch {
      $hasFilterRepo = $false
    }
  }
  if ($hasFilterRepo) {
    git filter-repo --invert-paths `
      --path pfx.b64 `
      --path graph_config.json `
      --path graph_config.inline.json `
      --path Export-PrivateKey.ps1
    Write-Host "History rewritten. Force-push required: git push --force --tags" -ForegroundColor Red
  } else {
    Write-Host "git-filter-repo not available; skipping history rewrite." -ForegroundColor Yellow
  }
}

Write-Host "Hardening complete." -ForegroundColor Green
