# Splits ALL_KEYS.env (repo root) into the 9 real per-business .env files it
# describes. Run this after filling in ALL_KEYS.env, before starting the
# connector locally or running push.sh.
#
# Usage:  powershell -File deploy/apply-keys.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Master = Join-Path $RepoRoot "ALL_KEYS.env"

if (-not (Test-Path $Master)) {
    Write-Error "ALL_KEYS.env not found at $Master"
    exit 1
}

$lines = Get-Content $Master
$currentPath = $null
$currentLines = New-Object System.Collections.Generic.List[string]

function Flush-Section($path, $bodyLines) {
    if (-not $path) { return }
    $dest = Join-Path $RepoRoot $path
    $destDir = Split-Path -Parent $dest
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        Write-Host "created $destDir"
    }
    # Trim leading/trailing blank lines from the section body.
    $body = ($bodyLines -join "`n").Trim() + "`n"
    Set-Content -Path $dest -Value $body -NoNewline -Encoding utf8
    Write-Host "wrote   $path"
}

foreach ($line in $lines) {
    if ($line -match '^### FILE:\s*(.+?)\s*$') {
        Flush-Section $currentPath $currentLines
        $currentPath = $matches[1]
        $currentLines.Clear()
        continue
    }
    if ($null -eq $currentPath) { continue }         # skip the top banner comment block
    if ($line -match '^# =====' -or $line -match '^# RUNTIME KNOBS') { break }  # stop at trailing reference section
    $currentLines.Add($line)
}
Flush-Section $currentPath $currentLines

Write-Host ""
Write-Host "Done. Real secrets now live in their per-business config/ folders (all git-ignored)."
Write-Host "Next: restart the connector locally, or ./deploy/push.sh root@24.199.81.124 to sync to the box."
