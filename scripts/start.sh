#!/usr/bin/env bash
# Start Odie in this terminal. Its home is ~/.odie (chats, settings, keys, logs), on port 8000 (the phone's address
# through Tailscale). The first start sets it up; every start after that carries on where it left off.
# Ctrl-C stops it (its voice worker too). To start over from nothing: Ctrl-C, then rm -rf ~/.odie
# Once live Odie runs as a service (scripts/install.sh, then the odie command), this folder is for development: it
# defaults to ~/odie-dev on port 8001 instead, so it never collides with live Odie, and says so.
#   scripts/start.sh                 Odie at ~/.odie (or ~/odie-dev beside a live service)
#   ODIE_HOME=~/elsewhere scripts/start.sh   another home (scripts/fresh.sh <name> does this for test runs)
#   ODIE_PORT=8001 scripts/start.sh  another port
# The environment it starts with (voice worker port, the phone's address, the pairing link) is set up by
# `odie serve` (odie/cli.py), the same code the service runs.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -d "$HOME/.odie/app/.git" ]; then  # scripts/install.sh put live Odie's own copy there
  LIVE_SERVICE=1; DEFAULT_HOME="$HOME/odie-dev"; DEFAULT_PORT=8001
else
  LIVE_SERVICE=0; DEFAULT_HOME="$HOME/.odie"; DEFAULT_PORT=8000
fi
HOME_DIR="${ODIE_HOME:-$DEFAULT_HOME}"
HOME_DIR="${HOME_DIR/#\~/$HOME}"
PORT="${ODIE_PORT:-$DEFAULT_PORT}"
if [ "$LIVE_SERVICE" = 1 ]; then
  echo "Live Odie runs as a service here (odie status), so this is a development Odie: ${HOME_DIR/#$HOME/~} on port $PORT."
fi
if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/health"; then
  echo "Something already answers on port $PORT (another Odie? another app?). Stop it first, or set ODIE_PORT."; exit 1
fi
if [ -d "$HOME_DIR/data" ]; then echo "Odie at $HOME_DIR, carrying on."; else echo "A new Odie at $HOME_DIR: setup opens in the browser."; fi
if [ "${ODIE_VOICE:-on}" != "off" ] && [ ! -x voice_server/.venv/bin/uvicorn ]; then
  echo "Setting up local voices (once)…"; (cd voice_server && uv sync --frozen >/dev/null)
fi
if [ -z "${FRESH_NO_BUILD:-}" ]; then
  BUILD_LOG="$(mktemp)"
  (cd web && npm run build >"$BUILD_LOG" 2>&1) || { echo "The web build failed:"; tail -30 "$BUILD_LOG"; rm -f "$BUILD_LOG"; exit 1; }
  rm -f "$BUILD_LOG"
fi
echo "Stop: Ctrl-C.  Start again: scripts/start.sh.  Start over: Ctrl-C, then rm -rf ${HOME_DIR/#$HOME/~}"
export ODIE_HOME="$HOME_DIR" ODIE_PORT="$PORT"
exec uv run python -m odie.cli serve
