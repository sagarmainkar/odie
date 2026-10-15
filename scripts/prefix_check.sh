#!/usr/bin/env bash
# Checks that Odie's requests to the model only ever add to the one before (so every provider's prompt cache is reused):
#   scripts/prefix_check.sh <folder of saved requests>          e.g. ~/.odie/data/requests (read only)
#   scripts/prefix_check.sh run ollama/glm-5.3-flash:cloud --turns evals/chats/prefix-check.turns.json [--thinking]
# `run` replays the chat through the real runner on a throwaway home (keys read from Odie's .env, never written) and
# keeps every request under ./.measure/. See odie/prefix_check.py.
set -euo pipefail
cd "$(dirname "$0")/.."
export ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
exec uv run python -m odie.prefix_check "$@"
