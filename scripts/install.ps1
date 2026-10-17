<#
 Folivox installer for Windows (PowerShell 5.1 or 7).
   From a checkout:   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
   Without one:       irm https://raw.githubusercontent.com/vatavale/folivox/main/scripts/install.ps1 | iex
   Options (environment): FOLIVOX_SOURCE=<path|git url|package>  FOLIVOX_SKIP_MODELS=1
 Safe to run again. Installs for the current user only; no administrator rights, nothing runs in the background.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# PowerShell 5.1 on older .NET defaults to TLS 1.0/1.1, which GitHub and astral.sh refuse
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
# Keep this file pure ASCII: PS 5.1 reads a BOM-less file as ANSI, and a BOM can break irm | iex. Cyrillic is built from char codes.
$CyrYes = "" + [char]0x434 + [char]0x414  # Cyrillic d / D ("da")
$CyrNo  = "" + [char]0x43D + [char]0x41D  # Cyrillic n / N ("net")
$Total = 5
function Step($n, $t) { Write-Host "`n[$n/$Total] $t" -ForegroundColor White }
function Ok($t)   { Write-Host "  v $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  ! $t" -ForegroundColor Yellow }
function Die($t)  { Write-Host "`nx $t" -ForegroundColor Red; throw "Folivox installation stopped" }  # throw, not exit: exit would close the window under irm | iex
function Has($c)  { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function RefreshPath { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }

Write-Host "Folivox installer (Windows)" -ForegroundColor White

# `folivox update` starts this script and exits: wait until the running folivox is gone, or uv cannot replace its files.
if ($env:FOLIVOX_WAIT_PID) {
  Write-Host "Waiting for folivox to close..."
  foreach ($p in ($env:FOLIVOX_WAIT_PID -split ",")) { if ($p -match '^\d+$') { Wait-Process -Id ([int]$p) -Timeout 60 -ErrorAction SilentlyContinue } }
}

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
$torch = "torch<2.6"  # the tested version; RTX 50 cards need 2.7 (below)
$gpuOk = $false
try { $gpuOk = (Has nvidia-smi) -and ($null -ne (nvidia-smi 2>$null)) } catch { }  # under Stop, PS 5.1 throws on native stderr
if ($gpuOk) {
  $gpuName = ""
  try { $gpuName = "" + (nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1) } catch { }
  Ok ("NVIDIA GPU found: " + $gpuName)
  # RTX 50 (Blackwell, compute capability 12.x / 10.x) has no kernels in builds before PyTorch 2.7 + CUDA 12.8:
  # "CUDA error: no kernel image is available". Older drivers lack compute_cap, so the name is the fallback.
  $caps = @(); $names = @()
  try { $caps = @(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null) } catch { }
  try { $names = @(nvidia-smi --query-gpu=name --format=csv,noheader 2>$null) } catch { }
  $blackwell = (@($caps | Where-Object { "$_" -match '^\s*1[0-9]\.' }).Count -gt 0) -or
               (@($names | Where-Object { "$_" -match 'RTX 50[0-9]0|Blackwell' }).Count -gt 0)
  if ($blackwell) {
    Ok "RTX 50 series: using the PyTorch build for CUDA 12.8"
    $torch = "torch==2.7.1"
    $extra = @("--index-strategy","unsafe-best-match","--extra-index-url","https://download.pytorch.org/whl/cu128")
  } else {
    $extra = @("--index-strategy","unsafe-best-match","--extra-index-url","https://download.pytorch.org/whl/cu121")
  }
} else {
  Warn "No NVIDIA GPU: the CPU build of PyTorch is used (synthesis is slow without a GPU)"
}

Step 4 "Installing Folivox (a few minutes: PyTorch is large)"
# Python: uv's own build by default. Smart App Control / WDAC on Windows 11 blocks that unsigned python.exe
# ("os error 4551", issue #4); then fall back to the signed python.org build (found, or installed with winget).
function RunsPy($exe) {
  if (-not $exe -or -not (Test-Path $exe)) { return $false }
  $ErrorActionPreference = "Continue"
  try { & $exe -c "import sys" *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function FindPy($pref) {
  $ErrorActionPreference = "Continue"
  try { $p = "" + (& uv python find --python-preference $pref ">=3.10,<3.13" 2>$null | Select-Object -First 1) } catch { $p = "" }
  if ($p -and (RunsPy $p.Trim())) { return $p.Trim() } else { return $null }
}
$ErrorActionPreference = "Continue"
try { & uv python install 3.12 *> $null } catch { }
$ErrorActionPreference = "Stop"
$pyExe = FindPy "only-managed"
if (-not $pyExe) {
  Warn "Windows blocked the Python that uv downloads (Smart App Control or another app control policy). Using Python from python.org instead."
  $pyExe = FindPy "only-system"
  if (-not $pyExe -and (Has winget)) {
    Write-Host "  installing Python 3.12 with winget (signed python.org build, for your user)..."
    winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements | Out-Null
    RefreshPath
    $pyExe = FindPy "only-system"
  }
  if (-not $pyExe) { Die "No usable Python 3.10-3.12. Install Python 3.12 from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH'), open a new PowerShell window and run this script again." }
}
Ok ("Python: " + $pyExe)
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
$constraints = Join-Path ([IO.Path]::GetTempPath()) "folivox-torch.txt"
[IO.File]::WriteAllLines($constraints, [string[]]@($torch, ($torch -replace '^torch', 'torchaudio')))  # no BOM
& uv tool install --force --refresh-package folivox --python $pyExe --constraints $constraints @extra $spec
$code = $LASTEXITCODE
Remove-Item $constraints -ErrorAction SilentlyContinue
$LASTEXITCODE = $code
if ($LASTEXITCODE -ne 0) { Die "Installation failed (the reason is in the lines above). If it is a network error, run this script again; it is safe to repeat. If it says 'Application Control policy', see https://github.com/vatavale/folivox/blob/main/docs/install.md#windows-smart-app-control" }
# update-shell writes "already in PATH" to stderr; under Stop, PowerShell 5.1 turns that into a terminating error even with 2>$null
$ErrorActionPreference = "Continue"
try { & uv tool update-shell *> $null } catch { }
$ErrorActionPreference = "Stop"
RefreshPath; $env:Path += ";$HOME\.local\bin"
if (-not (Has folivox)) { Die "Installed, but the 'folivox' command is not on PATH. Open a new PowerShell window and run: folivox setup" }
Ok "folivox installed"

Step 5 "Models and first check"
$env:PYTHONIOENCODING = "utf-8"
if ($env:FOLIVOX_SKIP_MODELS -eq "1") { folivox setup --skip-models } else { folivox setup }
if ($LASTEXITCODE -ne 0) { Die "Folivox itself is installed, but setup (model download and checks) did not finish. Run  folivox setup  again (it needs the network), or  folivox doctor  to see what is wrong." }
# Optional native C++ runtime (audio.cpp): only on request, FOLIVOX_NATIVE=1 (otherwise `folivox setup` asked, or: folivox runtime install)
if ($env:FOLIVOX_NATIVE -eq "1") { folivox runtime install --yes; if ($LASTEXITCODE -ne 0) { Warn "Native runtime not installed. Later: folivox runtime install" } }
# Optional Fish Audio engines (separate licences, 7-24 GB). Asked only of a person at a console, only where a tested build fits.
$fishBuild = ""
try { $fishBuild = ((& folivox engines best 2>$null) | Out-String).Trim() } catch { }
if ($fishBuild -and $env:FOLIVOX_NO_START -ne "1" -and -not $env:CI -and -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected) {
  Write-Host "`nOptional: Fish Audio engines (more natural voices, several speakers in one book)." -ForegroundColor White
  Write-Host "  They are not part of Folivox: a separate download from Hugging Face under the vendor's licence."
  Write-Host "  Personal use is free; selling audiobooks needs a commercial licence (details are shown before the download)."
  $fishAnswer = Read-Host "  Install $fishBuild now? You will see the licence first. [y/N]"
  if ($fishAnswer -match "^[yY$CyrYes]") { folivox engines install $fishBuild; if ($LASTEXITCODE -ne 0) { Warn "Fish engine not installed. Later: folivox engines install $fishBuild" } }
}
Write-Host "`nIf 'folivox' is not found in a new window: run  uv tool update-shell  and reopen PowerShell." -ForegroundColor White
# Offer to open the studio, only for a person at a console (not agents, CI or redirected input). FOLIVOX_NO_START=1 skips it.
if ($env:FOLIVOX_NO_START -ne "1" -and -not $env:CI -and -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected) {
  $answer = Read-Host "`nStart the studio now? [Y/n]"
  if ($answer -notmatch "^[nN$CyrNo]") { folivox ui }
}
if ($env:FOLIVOX_SELF_DELETE -eq "1" -and $MyInvocation.MyCommand.Path -and ((Split-Path -Leaf (Split-Path -Parent $MyInvocation.MyCommand.Path)) -like "folivox-update-*")) {  # only the temp folder `folivox update` made
  Remove-Item (Split-Path -Parent $MyInvocation.MyCommand.Path) -Recurse -Force -ErrorAction SilentlyContinue }
if ($env:FOLIVOX_WAIT_PID) { Read-Host "`nDone. Press Enter to close" | Out-Null }
