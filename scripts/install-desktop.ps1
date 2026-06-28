<#
  install-desktop.ps1 — set up cc-context-usage for Claude Desktop (Cowork) on Windows.

    1. create a venv and install this package
    2. merge the `cc-context` MCP server into claude_desktop_config.json
       (timestamped backup; validates JSON shape; preserves existing mcpServers entries)
    3. print how to restart Claude Desktop

  Usage:
    powershell -ExecutionPolicy Bypass -File scripts\install-desktop.ps1 `
        [-VenvDir <path>] [-ConfigPath <path>] [-PythonExe <path-or-name>]

  Note: by default this auto-detects a *working* interpreter (tries the `py` launcher,
  then `python`, then `python3`) and ignores the Microsoft Store alias stub that ships as
  `python` on many Windows installs. Override with -PythonExe py or
  -PythonExe "C:\Path\to\python.exe" if you want a specific one.
#>
param([string]$VenvDir, [string]$ConfigPath, [string]$PythonExe)

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

function Resolve-PythonExe {
  # Return the absolute path of a *working* python.exe, or $null. Rejects the Microsoft
  # Store alias stub (which fails to actually run `-c`). Tries the preferred name first,
  # else the py launcher, then python/python3.
  param([string]$Preferred)
  $tries = if ($Preferred) { @($Preferred) } else { @("py", "python", "python3") }
  foreach ($t in $tries) {
    $probe = @("-c", "import sys; print(sys.executable)")
    if ($t -ieq "py") { $probe = @("-3") + $probe }
    try {
      $out = & $t @probe 2>$null
      if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($out)) {
        $exe = ($out | Select-Object -First 1).Trim()
        if (Test-Path $exe) { return $exe }
      }
    } catch { }
  }
  return $null
}

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $VenvDir) { $VenvDir = Join-Path $Repo ".venv" }

$RealPy = Resolve-PythonExe $PythonExe
if (-not $RealPy) {
  throw @"
No working Python interpreter found.
'python' on PATH may be the Microsoft Store alias stub (it does not actually run Python).
Fix one of:
  - install Python:  winget install Python.Python.3.12   (or python.org, tick 'Add to PATH')
    then re-run this script (it auto-detects the 'py' launcher / python), or
  - pass one explicitly:  -PythonExe py   |   -PythonExe C:\path\to\python.exe
"@
}

Write-Host "==> Creating venv at $VenvDir and installing the package (python: $RealPy)"
& $RealPy -m venv $VenvDir
$Py = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $Py)) {
  throw "venv creation did not produce '$Py' (interpreter '$RealPy' may have failed). Try: -PythonExe py"
}
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
