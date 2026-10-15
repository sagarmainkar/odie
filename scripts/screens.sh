#!/usr/bin/env bash
# Screenshots of every screen at phone width, light and dark, from this folder's code: a look before a release.
# Starts a throwaway Odie (its own home in a temporary folder, its own port, no voices, no embedding service, no
# background jobs, no pairing, no model), photographs it with web/scripts/screens.mjs, then stops it and deletes the
# home. It never touches an installed Odie or its data.
#   scripts/screens.sh                    (the pictures go to a new temporary folder; the path is printed)
#   scripts/screens.sh ~/Desktop/screens  (or a folder you name)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-$(mktemp -d)/screens}"
PORT="${ODIE_SCREENS_PORT:-8077}"
ROOT="$(mktemp -d)"
if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/health"; then
  echo "Something already answers on port $PORT: stop it, or set ODIE_SCREENS_PORT."; exit 1
fi

echo "Building the web app…"
(cd web && npm run build >"$ROOT/build.log" 2>&1) || { echo "The web build failed:"; tail -20 "$ROOT/build.log"; exit 1; }

echo "Starting a throwaway Odie on port ${PORT}…"
# A model address nothing answers on, so no screen shows a model from this computer.
ODIE_HOME="$ROOT/home" ODIE_PORT="$PORT" ODIE_VOICE=off ODIE_EMBED=off ODIE_SCHEDULER=0 ODIE_PAIRING=off \
  LM_STUDIO_BASE_URL="http://127.0.0.1:9/v1" OLLAMA_BASE_URL="http://127.0.0.1:9/v1" \
  uv run python -m odie.cli serve >"$ROOT/server.log" 2>&1 &
SERVER=$!
stop() {
  kill "$SERVER" 2>/dev/null || true
  wait "$SERVER" 2>/dev/null || true
  rm -rf "$ROOT"
}
trap stop EXIT

for _ in $(seq 1 60); do
  if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/health"; then break; fi
  sleep 1
done
if ! curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/health"; then
  echo "Odie didn't start. Its log:"; tail -20 "$ROOT/server.log"; exit 1
fi

# First run: Setup as a new user sees it. Then setup is marked done in the throwaway home, for the other screens.
node web/scripts/screens.mjs "http://127.0.0.1:$PORT" "$OUT" setup
ODIE_HOME="$ROOT/home" uv run python -c "from odie import config; from odie.setup import state; from odie.store.db import Store
state.finish(Store(config.settings.db_path))"
node web/scripts/screens.mjs "http://127.0.0.1:$PORT" "$OUT" today,chat,sample,brain,settings
