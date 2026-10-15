#!/usr/bin/env bash
# A live check of one model path: a tool call, its answer, a second turn after Odie shortens the history, a skill
# loaded mid-turn, one background-style turn, and the cached share. --thinking: with the chat's "think longer" toggle
# on. Uses the keys in Odie's .env (~/.odie, or ODIE_HOME) and throwaway data folders (the OpenAI-style path saves its
# last requests in the data folder); a few tiny requests. Run it before merging anything that touches the model layer.
#   scripts/model_check.sh anthropic/claude-sonnet-5-5 [--thinking]
#   scripts/model_check.sh ollama/glm-5.3-flash:cloud
set -euo pipefail
cd "$(dirname "$0")/.."
export ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
export ODIE_DATA_DIR="$(mktemp -d -t odie-model-check)"  # never Odie's own data folder
exec uv run python -m odie.model_check "$@"
