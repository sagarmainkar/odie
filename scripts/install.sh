#!/usr/bin/env bash
# Install live Odie on this Mac, or reinstall it over an existing install. It puts Odie's own copy of the code in
# <home>/app at the newest release, builds it, writes the `odie` command and starts the background service (which then
# starts at every login). Data already in the home folder (chats, settings, keys) carries over. From the work folder:
#   scripts/install.sh
# Everything it writes comes from these settings, so a trial install beside the real one can use scratch values:
#   ODIE_HOME (~/.odie)   ODIE_SERVICE_LABEL (dev.odie.server)   ODIE_PORT (8000)   ODIE_BIN_DIR (~/.local/bin)
#   ODIE_REPO (this folder's origin)   ODIE_BRANCH (releases: the newest tag like v0.2.0; or a branch, e.g. main)
# and the service keeps these if they're set now: ODIE_VOICE=off (no local voice worker), ODIE_EMBED=on (build Odie's
# own embedding service; off by default, Ollama's EmbeddingGemma 2 does the job), ODIE_PAIRING, ODIE_SCHEDULER.
# It refuses to run while something else answers on the port (scripts/start.sh in a terminal): stop that first.
set -euo pipefail
ORIGINAL_PATH="$PATH"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
WORK_FOLDER="$(cd "$(dirname "$0")/.." && pwd)"
ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
ODIE_HOME="${ODIE_HOME/#\~/$HOME}"
ODIE_SERVICE_LABEL="${ODIE_SERVICE_LABEL:-dev.odie.server}"
ODIE_PORT="${ODIE_PORT:-8000}"
ODIE_BIN_DIR="${ODIE_BIN_DIR:-$HOME/.local/bin}"
ODIE_BIN_DIR="${ODIE_BIN_DIR/#\~/$HOME}"
ODIE_BRANCH="${ODIE_BRANCH:-releases}"
REPO="${ODIE_REPO:-$(git -C "$WORK_FOLDER" remote get-url origin)}"
APP="$ODIE_HOME/app"
LOG="$ODIE_HOME/logs/install.log"
export ODIE_HOME ODIE_SERVICE_LABEL ODIE_PORT ODIE_BIN_DIR ODIE_BRANCH

# 1. The tools it needs.
for tool in git uv npm; do
  command -v "$tool" >/dev/null || { echo "$tool is missing: brew install $tool"; exit 1; }
done

# 2. The port has to be free, or held by this install's own service (a reinstall).
LISTENER="$(lsof -nP -t -iTCP:"$ODIE_PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
SERVICE_PID="$(launchctl print "gui/$(id -u)/$ODIE_SERVICE_LABEL" 2>/dev/null | awk '$1 == "pid" && $2 == "=" {print $3; exit}' || true)"
if [ -n "$LISTENER" ] && [ "$LISTENER" != "$SERVICE_PID" ]; then
  echo "Something else answers on port $ODIE_PORT (scripts/start.sh in a terminal?). Stop it first, then run this again."
  exit 1
fi

# 3. Odie's own copy of the code, at the newest release (or the newest $ODIE_BRANCH).
mkdir -p -m 700 "$ODIE_HOME"
mkdir -p "$ODIE_HOME/logs"
echo "== install $(date '+%F %T') from $REPO ($ODIE_BRANCH)" >>"$LOG"
if [ -d "$APP/.git" ]; then
  echo "Refreshing ${APP}…"
  git -C "$APP" remote set-url origin "$REPO"
  git -C "$APP" fetch -q --tags origin
else
  echo "Copying Odie into ${APP}…"
  git clone -q "$REPO" "$APP"
fi
TARGET="origin/$ODIE_BRANCH"
if [ "$ODIE_BRANCH" = "releases" ]; then
  # The newest tag shaped like v1.2.3, by version number (v0.10.0 after v0.9.0); main when there's no release yet.
  NEWEST="$(git -C "$APP" tag -l 'v*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1 || true)"
  TARGET="${NEWEST:-origin/main}"
fi
git -C "$APP" checkout -q --force --detach "$TARGET"
echo "Version: $(git -C "$APP" log -1 --format='%h %s' | cut -c1-72)"

# 4. Build it: Python packages, the voice worker's (unless ODIE_VOICE=off) and the web app. Output goes to the log.
build_in() {
  local folder="$1"; shift
  echo "\$ (in $folder) $*" >>"$LOG"
  if ! (cd "$folder" && "$@") >>"$LOG" 2>&1; then
    echo "$* failed in $folder. The end of $LOG:"; tail -20 "$LOG"; exit 1
  fi
}
echo "Building (a few minutes the first time; details in $LOG)…"
build_in "$APP" uv sync --frozen
if [ "${ODIE_VOICE:-on}" != "off" ]; then build_in "$APP/voice_server" uv sync --frozen; fi
case "${ODIE_EMBED:-off}" in on|1|yes) build_in "$APP/embed_server" uv sync --frozen ;; esac  # Odie's own embedding service: opt-in
build_in "$APP/web" npm ci
build_in "$APP/web" npm run build

# 5. The odie command, then the service: started (or restarted) and checked.
"$APP/.venv/bin/python" -P -m odie.cli write-command
"$ODIE_BIN_DIR/odie" restart

case ":$ORIGINAL_PATH:" in
  *":$ODIE_BIN_DIR:"*) echo "Done. Try: odie status" ;;
  *) echo "Done. $ODIE_BIN_DIR isn't on your PATH yet: add it in ~/.zshrc, or run $ODIE_BIN_DIR/odie status" ;;
esac
