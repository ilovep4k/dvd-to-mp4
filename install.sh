#!/usr/bin/env bash
# install.sh — dvd2mp4 macOS installer
# Installs all system dependencies and sets up the Python environment.
# Usage: ./install.sh
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${BOLD}==> $*${RESET}"; }
success() { echo -e "${GREEN}✓  $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠  $*${RESET}"; }
die()     { echo -e "${RED}✗  $*${RESET}" >&2; exit 1; }

# ── 1. macOS only ─────────────────────────────────────────────────────────────
[[ "$(uname)" == "Darwin" ]] || die "This installer currently supports macOS only."

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"

echo ""
echo -e "${BOLD}dvd2mp4 macOS Installer${RESET}"
echo "────────────────────────────────────────"
echo ""

# ── 2. Homebrew ───────────────────────────────────────────────────────────────
info "Checking for Homebrew..."
if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi
success "Homebrew found: $(brew --version | head -1)"

# ── 3. System dependencies ────────────────────────────────────────────────────
info "Installing system dependencies via Homebrew..."
brew install ffmpeg vapoursynth ffms2
success "ffmpeg, vapoursynth, ffms2 installed"

# ── 4. ffms2 → VapourSynth plugin symlink ────────────────────────────────────
info "Linking ffms2 into VapourSynth plugin directory..."
FFMS2_LIB="$(brew --prefix ffms2)/lib/libffms2.dylib"
VS_PLUGIN_DIR="$(brew --prefix vapoursynth)/lib/vapoursynth"
mkdir -p "$VS_PLUGIN_DIR"
if [[ -f "$FFMS2_LIB" ]]; then
    if [[ ! -e "$VS_PLUGIN_DIR/libffms2.dylib" ]]; then
        ln -s "$FFMS2_LIB" "$VS_PLUGIN_DIR/libffms2.dylib"
        success "ffms2 symlink created"
    else
        success "ffms2 symlink already exists"
    fi
else
    warn "libffms2.dylib not found at $FFMS2_LIB — skipping symlink"
fi

# ── 5. Locate brew Python (>=3.10) ────────────────────────────────────────────
# Must use brew's Python so the venv can see brew-installed vapoursynth bindings.
info "Locating Python 3.10+..."
BREW_PREFIX="$(brew --prefix)"
BREW_PYTHON=""

for ver in 3.14 3.13 3.12 3.11 3.10; do
    candidate="$BREW_PREFIX/opt/python@$ver/bin/python3"
    if [[ -x "$candidate" ]]; then
        BREW_PYTHON="$candidate"
        break
    fi
done

if [[ -z "$BREW_PYTHON" ]] && [[ -x "$BREW_PREFIX/bin/python3" ]]; then
    BREW_PYTHON="$BREW_PREFIX/bin/python3"
fi

if [[ -z "$BREW_PYTHON" ]]; then
    warn "brew python3 not found — installing python@3.12..."
    brew install python@3.12
    BREW_PYTHON="$(brew --prefix python@3.12)/bin/python3"
fi

PY_VER=$("$BREW_PYTHON" -c "import sys; print(sys.version_info.minor)")
PY_MAJ=$("$BREW_PYTHON" -c "import sys; print(sys.version_info.major)")
if [[ "$PY_MAJ" -lt 3 ]] || [[ "$PY_VER" -lt 10 ]]; then
    warn "brew python ($PY_MAJ.$PY_VER) is too old — installing python@3.12..."
    brew install python@3.12
    BREW_PYTHON="$(brew --prefix python@3.12)/bin/python3"
fi
success "Using Python: $("$BREW_PYTHON" --version)"

# ── 6. Create virtual environment ─────────────────────────────────────────────
# --system-site-packages lets the venv see brew-installed vapoursynth bindings.
# Venvs are exempt from PEP 668, so pip works freely inside them.
info "Creating virtual environment at $VENV_DIR..."
if [[ -d "$VENV_DIR" ]]; then
    warn "Existing .venv found — removing and recreating..."
    rm -rf "$VENV_DIR"
fi
"$BREW_PYTHON" -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
success "Virtual environment created"

# ── 7. Install vsrepo ─────────────────────────────────────────────────────────
# vsrepo is not on PyPI and not bundled with the brew vapoursynth formula.
# Download the script directly from the VapourSynth GitHub repo.
info "Installing vsrepo (VapourSynth plugin manager)..."
VSREPO="$VENV_DIR/bin/vsrepo.py"
curl -fsSL "https://raw.githubusercontent.com/vapoursynth/vsrepo/master/vsrepo.py" -o "$VSREPO"
# Install vsrepo's own dependencies into the venv
"$VENV_DIR/bin/pip" install --quiet requests tqdm
VSREPO_CMD="$VENV_DIR/bin/python3 $VSREPO"
success "vsrepo downloaded"

# ── 8. Install VapourSynth plugins ────────────────────────────────────────────
info "Updating vsrepo package list..."
$VSREPO_CMD update
info "Installing VapourSynth plugins (havsfunc, mvtools, nnedi3)..."
$VSREPO_CMD install havsfunc mvtools nnedi3
success "VapourSynth plugins installed"

# ── 9. Install dvd2mp4 ────────────────────────────────────────────────────────
info "Installing dvd2mp4..."
"$VENV_DIR/bin/pip" install --quiet -e "$REPO_DIR"
success "dvd2mp4 installed"

# ── 10. Verify ────────────────────────────────────────────────────────────────
info "Verifying all dependencies..."
if "$VENV_DIR/bin/dvd2mp4" --check-deps; then
    success "All dependencies verified"
else
    warn "Some dependencies are missing — see output above."
fi

# ── 11. Done ──────────────────────────────────────────────────────────────────
SHELL_RC="$HOME/.zshrc"
[[ "$SHELL" == */bash ]] && SHELL_RC="$HOME/.bashrc"

echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "Add dvd2mp4 to your PATH (one-time setup):"
echo ""
echo -e "  ${BOLD}echo 'export PATH=\"$VENV_DIR/bin:\$PATH\"' >> $SHELL_RC && source $SHELL_RC${RESET}"
echo ""
echo "Then:"
echo "  dvd2mp4              # Launch GUI"
echo "  dvd2mp4 movie.iso    # Convert via CLI"
echo "  dvd2mp4 --check-deps # Verify"
echo ""
echo "To update later:"
echo "  cd $REPO_DIR && git pull && $VENV_DIR/bin/pip install -e ."
echo ""
