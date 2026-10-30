#!/usr/bin/env bash
# Hack Lab toolchain installer. Idempotent. The SAME script runs on the Pi
# (via provisioning/install.sh, P5) and inside Dockerfile.dev, so the Mac
# compiles with exactly the Pi's toolchain.
#
# Requires: bash, curl, python3 (>= 3.11) with the venv module.
#   PREFIX               install root            (default /opt/hacklab)
#   REPO_DIR             checkout to install     (default: this script's repo)
#   ARDUINO_CLI_VERSION  pinned arduino-cli      (default 1.5.1)
#
# Produces:
#   $PREFIX/bin/arduino-cli           pinned binary
#   $PREFIX/arduino/arduino-cli.yaml  config: all arduino-cli state under $PREFIX/arduino
#   $PREFIX/venv                      Python venv with hacklab installed (editable)
set -euo pipefail

PREFIX="${PREFIX:-/opt/hacklab}"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ARDUINO_CLI_VERSION="${ARDUINO_CLI_VERSION:-1.5.1}"
ARDUINO_DIR="$PREFIX/arduino"
CLI="$PREFIX/bin/arduino-cli"
CFG="$ARDUINO_DIR/arduino-cli.yaml"

log() { printf '[toolchain] %s\n' "$*"; }

mkdir -p "$PREFIX/bin" "$ARDUINO_DIR"/{data,downloads,user}

# --- arduino-cli (pinned) ---------------------------------------------------
if [ -x "$CLI" ] && "$CLI" version 2>/dev/null | grep -q "Version: $ARDUINO_CLI_VERSION"; then
  log "arduino-cli $ARDUINO_CLI_VERSION already installed"
else
  log "installing arduino-cli $ARDUINO_CLI_VERSION into $PREFIX/bin"
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
    | BINDIR="$PREFIX/bin" sh -s "$ARDUINO_CLI_VERSION"
fi

# Keep every arduino-cli state directory under $PREFIX (no $HOME surprises
# under systemd), and never phone home for update checks.
cat > "$CFG" <<YAML
directories:
  data: $ARDUINO_DIR/data
  downloads: $ARDUINO_DIR/downloads
  user: $ARDUINO_DIR/user
updater:
  enable_notification: false
YAML

cli() { "$CLI" --config-file "$CFG" "$@"; }

log "installing arduino:avr core"
cli core update-index
cli core install arduino:avr

log "installing whitelisted libraries"
grep -vE '^\s*(#|$)' "$REPO_DIR/provisioning/libraries.txt" | while read -r lib; do
  cli lib install "$lib"
done

# --- Python venv -------------------------------------------------------------
if [ ! -x "$PREFIX/venv/bin/python" ]; then
  log "creating venv at $PREFIX/venv"
  python3 -m venv "$PREFIX/venv"
fi
log "installing hacklab from $REPO_DIR"
"$PREFIX/venv/bin/pip" install -q -e "${REPO_DIR}[dev]"

log "done: $(cli version | head -1), $("$PREFIX/venv/bin/python" --version)"
