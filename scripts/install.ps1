<#
 Folivox installer for Windows (PowerShell 5.1 or 7).
   From a checkout:   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
   Without one:       irm https://raw.githubusercontent.com/vatavale/folivox/main/scripts/install.ps1 | iex
   Options (environment): FOLIVOX_SOURCE=<path|git url|package>  FOLIVOX_SKIP_MODELS=1
 Safe to run again. Installs for the current user only; no administrator rights, nothing runs in the background.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Total = 5
function Step($n, $t) { Write-Host "`n[$n/$Total] $t" -ForegroundColor White }
function Ok($t)   { Write-Host "  v $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  ! $t" -ForegroundColor Yellow }
function Die($t)  { Write-Host "`nx $t" -ForegroundColor Red; throw "Folivox installation stopped" }  # throw, not exit: exit would close the window under irm | iex
function Has($c)  { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function RefreshPath { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }

Write-Host "Folivox installer (Windows)" -ForegroundColor White

Step 1 "Package manager (uv)"
if (-not (Has uv)) {
  Write-Host "  uv not found, installing it for your user (https://astral.sh/uv)..."
  try { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression | Out-Null } catch { Die "Could not install uv (no network?). See https://docs.astral.sh/uv/" }
  RefreshPath; $env:Path += ";$HOME\.local\bin"
}
if (-not (Has uv)) { Die "uv was installed but is not on PATH. Open a new PowerShell window and run this script again." }
Ok ("uv " + ((uv --version) -replace "uv ",""))

Step 2 "ffmpeg (builds the audiobook file)"
if (-not (Has ffmpeg)) {
  if (Has winget) {
    Write-Host "  installing with winget..."
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements | Out-Null
    RefreshPath
  }
  if (-not (Has ffmpeg)) { Die "ffmpeg is missing. Run: winget install Gyan.FFmpeg   then open a new PowerShell window and run this script again." }
}
Ok ((ffmpeg -version | Select-Object -First 1))

Step 3 "Your computer"
$extra = @()
if ((Has nvidia-smi) -and ((nvidia-smi 2>$null) -ne $null)) {
  Ok ("NVIDIA GPU found: " + (nvidia-smi --query-gpu=name --format=csv,noheader | Select-Object -First 1))
  $extra = @("--index-strategy","unsafe-best-match","--extra-index-url","https://download.pytorch.org/whl/cu121")
} else {
  Warn "No NVIDIA GPU: the CPU build of PyTorch is used (synthesis is slow without a GPU)"
}

Step 4 "Installing Folivox (a few minutes: PyTorch is large)"
$here = if ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { $null }  # $null under irm | iex
$src = $env:FOLIVOX_SOURCE
if (-not $src) {
  $py = if ($here) { Join-Path $here "..\pyproject.toml" } else { $null }
  if ($py -and (Test-Path $py) -and (Select-String -Path $py -Pattern '^name = "folivox"' -Quiet)) { $src = (Resolve-Path (Join-Path $here "..")).Path }
  else { $src = "https://github.com/vatavale/folivox/archive/refs/heads/main.zip" }  # no checkout: install from the GitHub archive (no git needed)
}
if ($src -match '^(http|git\+)') { $spec = "folivox[all] @ $src" }
elseif (Test-Path (Join-Path $src "pyproject.toml")) { $spec = (Resolve-Path $src).Path + "[all]" }
else { $spec = "$src[all]" }
& uv tool install --force --refresh-package folivox --python ">=3.10,<3.13" @extra $spec
if ($LASTEXITCODE -ne 0) { Die "Installation failed. Check the network and run this script again; it is safe to repeat." }
& uv tool update-shell 2>$null | Out-Null
RefreshPath; $env:Path += ";$HOME\.local\bin"
if (-not (Has folivox)) { Die "Installed, but the 'folivox' command is not on PATH. Open a new PowerShell window and run: folivox setup" }
Ok "folivox installed"

Step 5 "Models and first check"
$env:PYTHONIOENCODING = "utf-8"
if ($env:FOLIVOX_SKIP_MODELS -eq "1") { folivox setup --skip-models } else { folivox setup }
Write-Host "`nIf 'folivox' is not found in a new window: run  uv tool update-shell  and reopen PowerShell." -ForegroundColor White
