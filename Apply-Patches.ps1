param(
    [string]$RepoRoot = ".",
    [switch]$Commit,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Note($msg, $color="Gray") { Write-Host $msg -ForegroundColor $color }
function Write-Ok($msg)  { Write-Note $msg "Green" }
function Write-Warn($msg){ Write-Note $msg "Yellow" }
function Write-Err($msg) { Write-Note $msg "Red" }

function Update-Content {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][ScriptBlock]$Transform
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn "Skip (missing): $Path"
        return $false
    }
    $orig = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $new  = & $Transform.Invoke($orig)
    if ($new -ne $orig) {
        if (-not $DryRun) { Set-Content -LiteralPath $Path -Value $new -Encoding UTF8 -NoNewline }
        Write-Ok "Patched: $Path"
        return $true
    } else {
        Write-Note "No changes: $Path"
        return $false
    }
}

# ---- Transform helpers -------------------------------------------------------
function Fix-LVars([string]$s) {
    $r = $s
    # Tighten to common patterns: for l in ..., l.get(...), l.url, l[...]
    $r = [regex]::Replace($r, '\bfor\s+l\s+in\b', 'for link in')
    $r = [regex]::Replace($r, '(^|[^A-Za-z0-9_])l\.get\(', '${1}link.get(')
    $r = [regex]::Replace($r, '(^|[^A-Za-z0-9_])l\.url\b', '${1}link.url')
    $r = [regex]::Replace($r, '(^|[^A-Za-z0-9_])l\[', '${1}link[')
    return $r
}
function Ensure-TypingAny([string]$s) {
    $r = $s
    # from typing import (A, B)
    $r = [regex]::Replace($r, 'from\s+typing\s+import\s+\(([^)]+)\)', {
        param($m)
        $list = $m.Groups[1].Value
        if ($list -notmatch '\bAny\b') { "from typing import ($list, Any)" } else { $m.Value }
    })
    # from typing import A, B
    $r = [regex]::Replace($r, 'from\s+typing\s+import\s+([^\r\n]+)', {
        param($m)
        if ($m.Value -notmatch '\bAny\b') { $m.Value + ', Any' } else { $m.Value }
    })
    # Fallback: if Any is used but not imported, inject minimal import at top
    if ($r -match '\bAny\b' -and $r -notmatch 'from\s+typing\s+import.*\bAny\b') {
        $r = "from typing import Any`r`n" + $r
    }
    return $r
}
function Remove-NSLines([string]$s) {
    $r = $s
    # Remove the stray "n#s = {...}" and the unused "ns = {...}" lines entirely
    $r = [regex]::Replace($r, '^\s*n#s\s*=.*\r?\n', '', 'Multiline')
    $r = [regex]::Replace($r, '^\s*ns\s*=\s*\{[^\r\n]*\}\s*\r?\n', '', 'Multiline')
    return $r
}
function Remove-UnusedItId([string]$s) {
    [regex]::Replace($s, '^\s*it_id\s*=.*\r?\n', '', 'Multiline')
}
function Fix-CSVWriter([string]$s) {
    [regex]::Replace($s, 'writeheader\(\);\s*w\.writerows\(', "writeheader()`r`n        w.writerows(", 'Multiline')
}
function Remove-UnusedImports-Streamlit([string]$s) {
    $r = $s
    $r = [regex]::Replace($r, '^\s*from\s+collections\s+import\s+Counter\s*,\s*defaultdict\s*\r?\n', '', 'Multiline')
    $r = [regex]::Replace($r, '^\s*from\s+datetime\s+import\s+datetime\s*\r?\n', '', 'Multiline')
    return $r
}
function Remove-ImportTime-InPage([string]$s) {
    [regex]::Replace($s, '^\s*import\s+time\s*\r?\n', '', 'Multiline')
}
function Split-MultiImports([string]$s) {
    $r = $s
    $r = [regex]::Replace($r, '^\s*import\s+([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*$', "import `$1`r`nimport `$2`r`nimport `$3", 'Multiline')
    $r = [regex]::Replace($r, '^\s*import\s+([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*$', "import `$1`r`nimport `$2", 'Multiline')
    return $r
}

# ---- Run patches -------------------------------------------------------------
$root = Resolve-Path -LiteralPath $RepoRoot

Write-Note "Repo root: $root"

$changed = @()

# 1) app/streamlit_app.py : fix E741 and optional unused-imports
$path = Join-Path $root "app/streamlit_app.py"
if (Update-Content -Path $path -Transform { param($txt) (Remove-UnusedImports-Streamlit (Fix-LVars $txt)) }) { $changed += $path }

# 2) app/pages/1_📊_Roadmap.py : remove unused 'time' import
$path = Join-Path $root "app/pages/1_📊_Roadmap.py"
if (Update-Content -Path $path -Transform { param($txt) (Remove-ImportTime-InPage $txt) }) { $changed += $path }

# 3) scripts/cli/generate_report.py : add Any, remove ns-lines, fix E741
$path = Join-Path $root "scripts/cli/generate_report.py"
if (Update-Content -Path $path -Transform { param($txt) (Fix-LVars (Remove-NSLines (Ensure-TypingAny $txt))) }) { $changed += $path }

# 4) scripts/cli/render_html.py : fix chips lambda var and remove unused it_id
$path = Join-Path $root "scripts/cli/render_html.py"
if (Update-Content -Path $path -Transform { param($txt) (Remove-UnusedItId (Fix-LVars $txt)) }) { $changed += $path }

# 5) tests/test_products_filter.py : split CSV write header/writerows to separate lines
$path = Join-Path $root "tests/test_products_filter.py"
if (Update-Content -Path $path -Transform { param($txt) (Fix-CSVWriter $txt) }) { $changed += $path }

# 6) Optional: split multi-imports flagged elsewhere
$optionals = @(
    (Join-Path $root "m365roadmap_ui/__main__.py"),
    (Join-Path $root "scripts/md_to_html.py")
)
foreach ($p in $optionals) {
    if (Test-Path -LiteralPath $p) {
        if (Update-Content -Path $p -Transform { param($txt) (Split-MultiImports $txt) }) { $changed += $p }
    }
}

if ($Commit -and $changed.Count -gt 0) {
    try {
        Push-Location $root
        git add -- $changed | Out-Null
        git commit -m "chore: apply patch set (fix E741, F821 Any, remove stray ns line, test E702, tidy imports)" | Out-Null
        Pop-Location
        Write-Ok "Changes committed."
    } catch {
        Write-Warn "Git commit skipped or failed: $($_.Exception.Message)"
    }
} elseif ($Commit) {
    Write-Warn "Nothing to commit."
}

Write-Note ("Patched files: {0}" -f ($changed -join ", "))
