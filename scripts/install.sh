#!/usr/bin/env bash
# Folivox installer for macOS and Linux.
#   From a checkout:   ./scripts/install.sh
#   Options (environment): FOLIVOX_SOURCE=<path|git url|package>  FOLIVOX_SKIP_MODELS=1
# Safe to run again. Installs for the current user only; no sudo, nothing runs in the background.
set -euo pipefail

if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; N=$'\033[0m'; else B=; G=; Y=; R=; C=; N=; fi
step() { printf '\n%s[%s/%s] %s%s\n' "$B" "$1" "$TOTAL" "$2" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
die()  { printf '\n%s✗ %s%s\n' "$R" "$1" "$N" >&2; exit 1; }
TOTAL=5

OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS" in Darwin|Linux) ;; *) die "Unsupported system: $OS. On Windows use scripts/install.ps1";; esac
printf '%sFolivox installer%s  (%s %s)\n' "$B" "$N" "$OS" "$ARCH"

# -- 1. uv ---------------------------------------------------------------------------------------
step 1 "Package manager (uv)"
if ! command -v uv >/dev/null 2>&1; then
  echo "  uv not found, installing it for your user (https://astral.sh/uv)…"
  command -v curl >/dev/null 2>&1 || die "curl is needed to install uv. Install curl, or install uv yourself: https://docs.astral.sh/uv/"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || die "Could not install uv (no network?). See https://docs.astral.sh/uv/"
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "uv was installed but is not on PATH. Open a new terminal and run this script again."
ok "uv $(uv --version | awk '{print $2}')"

# -- 2. ffmpeg -----------------------------------------------------------------------------------
step 2 "ffmpeg (builds the audiobook file)"
if command -v ffmpeg >/dev/null 2>&1; then
  ok "$(ffmpeg -version | head -1 | cut -d' ' -f1-3)"
else
  if [ "$OS" = Darwin ] && command -v brew >/dev/null 2>&1; then
    echo "  installing with Homebrew…"; brew install ffmpeg >/dev/null 2>&1 || die "brew could not install ffmpeg. Run: brew install ffmpeg"
  elif [ "$OS" = Linux ] && command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" = 0 ]; then
    apt-get install -y ffmpeg >/dev/null 2>&1 || die "apt could not install ffmpeg"
  else
    die "ffmpeg is missing. Install it, then run this script again:
     macOS:  brew install ffmpeg      (get Homebrew at https://brew.sh)
     Debian/Ubuntu:  sudo apt install ffmpeg      Fedora:  sudo dnf install ffmpeg"
  fi
  ok "ffmpeg installed"
fi

# -- 3. hardware → which PyTorch -----------------------------------------------------------------
step 3 "Your computer"
EXTRA=()
if [ "$OS" = Darwin ]; then
  if [ "$ARCH" = arm64 ]; then ok "Apple Silicon: the GPU is used (hybrid mode)"; else warn "Intel Mac: runs on the CPU only (slow)"; fi
elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  ok "NVIDIA GPU found: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
else
  warn "No NVIDIA GPU: using the smaller CPU build of PyTorch (synthesis is slow without a GPU)"
  EXTRA=(--index-strategy unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cpu)
fi

# -- 4. folivox ----------------------------------------------------------------------------------
step 4 "Installing Folivox (a few minutes: PyTorch is large)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [ -n "${FOLIVOX_SOURCE:-}" ]; then SRC="${FOLIVOX_SOURCE}"
elif [ -f "$HERE/../pyproject.toml" ] && grep -q '^name = "folivox"' "$HERE/../pyproject.toml"; then SRC="$HERE/.."
else SRC="folivox"; fi
case "$SRC" in
  http*|git+*) SPEC="folivox[all] @ $SRC" ;;
  *) if [ -e "$SRC/pyproject.toml" ]; then SPEC="$(cd "$SRC" && pwd)[all]"; else SPEC="$SRC[all]"; fi ;;
esac
uv tool install --force --python ">=3.10,<3.13" ${EXTRA[@]+"${EXTRA[@]}"} "$SPEC" || die "Installation failed. Check the network and run this script again; it is safe to repeat."
uv tool update-shell >/dev/null 2>&1 || true
export PATH="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin"):$PATH"
command -v folivox >/dev/null 2>&1 || die "Installed, but the 'folivox' command is not on PATH. Open a new terminal and run: folivox setup"
ok "folivox $(folivox --version 2>/dev/null || true)"

# -- 5. models + guide ---------------------------------------------------------------------------
step 5 "Models and first check"
if [ "${FOLIVOX_SKIP_MODELS:-0}" = 1 ]; then folivox setup --skip-models; else folivox setup; fi
printf '\n%sIf the command is not found in a new terminal:%s run  %suv tool update-shell%s  and reopen the terminal.\n' "$B" "$N" "$C" "$N"
