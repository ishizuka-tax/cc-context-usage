<#
  uninstall-desktop.ps1 — reverse scripts\install-desktop.ps1.

    1. remove the `cc-context` entry from claude_desktop_config.json
       (timestamped backup; preserves other mcpServers entries)
    2. remove the venv

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\uninstall-desktop.ps1 [-VenvDir <path>] [-ConfigPath <path>]
#>
param([string]$VenvDir, [string]$ConfigPath)

function Format-Json {
  # Re-indent ConvertTo-Json output to 2 spaces (PS 5.1 indents very wide). Whitespace-only.
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

Write-Host "NOTE: Quit Claude Desktop before running this. While it is running, its MCP server"
Write-Host "      process keeps files in the venv open (native .pyd/.dll), so venv removal will"
Write-Host "      fail with an access-denied error. (Removing the config entry still works.)"
Write-Host ""

$storeCfg = Join-Path $env:LOCALAPPDATA "Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json"
$classicCfg = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
if ($ConfigPath) {
  $cfg = $ConfigPath
} else {
  $cfg = @($storeCfg, $classicCfg) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if ($cfg -and (Test-Path $cfg)) {
  $stamp = Get-Date -Format "yyyyMMddHHmmssfff"
  Copy-Item $cfg "$cfg.cc-context.bak.$stamp" -Force
  $json = Get-Content $cfg -Raw | ConvertFrom-Json
  if (($json -is [pscustomobject]) -and
      ($json.PSObject.Properties.Name -contains "mcpServers") -and
      ($json.mcpServers -is [pscustomobject]) -and
      ($json.mcpServers.PSObject.Properties.Name -contains "cc-context")) {
    $json.mcpServers.PSObject.Properties.Remove("cc-context")
    # UTF-8 without BOM (Set-Content -Encoding UTF8 adds a BOM on PS 5.1, which breaks
    # Claude Desktop's JSON parser).
    $tmp = "$cfg.tmp.$([System.Guid]::NewGuid().ToString('N'))"
    $out = $json | ConvertTo-Json -Depth 10 | Format-Json
    [System.IO.File]::WriteAllText($tmp, $out, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -Force $tmp $cfg
    Write-Host "Removed cc-context from $cfg (backup at $cfg.cc-context.bak.$stamp)"
  } else {
    Write-Host "cc-context not present in $cfg; nothing to remove."
  }
} else {
  Write-Host "No claude_desktop_config.json found; nothing to remove."
}

if (Test-Path $VenvDir) {
  try {
    Remove-Item -Recurse -Force -ErrorAction Stop $VenvDir
    Write-Host "Removed venv $VenvDir"
  } catch {
    Write-Warning "Could not remove the venv at: $VenvDir"
    Write-Warning "This almost always means Claude Desktop (or a Python process from this venv) is"
    Write-Warning "still running and holding a file open (e.g. a native .pyd/.dll)."
    Write-Warning "Fix: fully quit Claude Desktop, then re-run this script (or delete the folder by"
    Write-Warning "hand). The config entry was already removed, so the MCP server is gone after the"
    Write-Warning "next Claude Desktop restart regardless of the leftover venv."
  }
}
Write-Host "Done. Restart Claude Desktop for the change to take effect."
