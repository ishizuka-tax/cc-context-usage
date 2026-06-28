<#
  install-desktop.ps1 — set up cc-context-usage for Claude Desktop (Cowork) on Windows.

    1. create a venv and install this package
    2. merge the `cc-context` MCP server into claude_desktop_config.json
       (timestamped backup; validates JSON shape; preserves existing mcpServers entries)
    3. print how to restart Claude Desktop

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\install-desktop.ps1 `
        [-VenvDir <path>] [-ConfigPath <path>] [-PythonExe <path-or-name>]

  Note: -PythonExe defaults to "python". On Windows where `python` is the Microsoft
  Store alias stub (no real interpreter), pass a real one, e.g. -PythonExe py
  (the Python launcher) or -PythonExe "C:\Path\to\python.exe".
#>
param([string]$VenvDir, [string]$ConfigPath, [string]$PythonExe = "python")

function Format-Json {
  # Re-indent ConvertTo-Json output to 2 spaces. Windows PowerShell 5.1's ConvertTo-Json
  # indents very wide, which is painful to hand-edit; this normalizes to standard 2-space
  # JSON. Whitespace-only (each token is on its own line), so the JSON stays valid.
  param([Parameter(Mandatory, ValueFromPipeline)][string]$Json)
  $indent = 0
  ($Json -split "`n" | ForEach-Object {
    $line = $_.Trim()
    if ($line -match '^[\}\]]') { $indent = [Math]::Max($indent - 1, 0) }
    $out = ('  ' * $indent) + $line
    if ($line -match '[\{\[]$') { $indent++ }
    $out
  }) -join "`r`n"
}

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $VenvDir) { $VenvDir = Join-Path $Repo ".venv" }

Write-Host "==> Creating venv at $VenvDir and installing the package (python: $PythonExe)"
& $PythonExe -m venv $VenvDir
$Py = Join-Path $VenvDir "Scripts\python.exe"
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install $Repo

# Locate claude_desktop_config.json.
#   -ConfigPath wins; else an existing file (Store-packaged path preferred, then classic);
#   else, for a fresh install, pick the Store path only if the Store package dir exists.
$storeDir = Join-Path $env:LOCALAPPDATA "Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
$storeCfg = Join-Path $storeDir "claude_desktop_config.json"
$classicCfg = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
if ($ConfigPath) {
  $cfg = $ConfigPath
} else {
  $existing = @($storeCfg, $classicCfg) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($existing) {
    $cfg = $existing
  } elseif (Test-Path $storeDir) {
    $cfg = $storeCfg      # Store-packaged Claude is installed but has no config yet
  } else {
    $cfg = $classicCfg
  }
}
New-Item -ItemType Directory -Force -Path (Split-Path $cfg) | Out-Null

Write-Host "==> Registering MCP server 'cc-context' in $cfg"
if (Test-Path $cfg) {
  $stamp = Get-Date -Format "yyyyMMddHHmmssfff"
  Copy-Item $cfg "$cfg.cc-context.bak.$stamp" -Force
  Write-Host "    backed up existing config to $cfg.cc-context.bak.$stamp"
  $json = Get-Content $cfg -Raw | ConvertFrom-Json
} else {
  $json = [pscustomobject]@{}
}

# Validate shapes before mutating, to avoid corrupting an unexpected config.
if ($json -isnot [pscustomobject]) {
  throw "Config root is not a JSON object: $cfg. Back it up and fix/remove it, then re-run."
}
if ($json.PSObject.Properties.Name -contains "mcpServers") {
  if ($json.mcpServers -isnot [pscustomobject]) {
    throw "mcpServers exists but is not a JSON object in $cfg; aborting to avoid corruption (a backup was made)."
  }
} else {
  $json | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) -Force
}

$entry = [pscustomobject]@{ command = $Py; args = @("-m", "cc_context.desktop") }
$json.mcpServers | Add-Member -NotePropertyName "cc-context" -NotePropertyValue $entry -Force

# Write to a temp file in the same directory, then move into place (avoid partial writes).
# Use .NET WriteAllText with UTF-8 *without BOM*: Windows PowerShell 5.1's
# `Set-Content -Encoding UTF8` prepends a BOM, which Claude Desktop's JSON parser rejects
# ("Unexpected token ... is not valid JSON"). This is BOM-free on both PS 5.1 and 7.
$tmp = "$cfg.tmp.$([System.Guid]::NewGuid().ToString('N'))"
$out = $json | ConvertTo-Json -Depth 10 | Format-Json
[System.IO.File]::WriteAllText($tmp, $out, (New-Object System.Text.UTF8Encoding($false)))
Move-Item -Force $tmp $cfg

Write-Host "==> Done. Restart Claude Desktop, e.g.:"
Write-Host "      Get-Process Claude -ErrorAction SilentlyContinue | Stop-Process -Force"
Write-Host "      Start-Process `"$env:LOCALAPPDATA\Programs\Claude\Claude.exe`""
Write-Host "    Then open a new Cowork session and ask Claude to run get_current_context_usage."
