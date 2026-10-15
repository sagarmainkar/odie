#!/usr/bin/env bash
# Which models draw the new blocks well (composable blocks, 5b): about 12 fixed questions through Odie's real runner,
# one fresh chat each, on a throwaway home. Only the provider's API key is read from Odie's .env (~/.odie, or
# ODIE_HOME); nothing is written there. Results: evals/blocks/<date>-<provider>-<model>.json and .md, and the grid in
# evals/blocks/README.md. Scoring uses the web app's parser, so web/ needs its packages (npm ci).
#   scripts/blocks_eval.sh ollama/glm-5.3-flash:cloud
#   scripts/blocks_eval.sh anthropic/claude-sonnet-5-5
#   scripts/blocks_eval.sh --rescore            score the saved replies again after a parser change (no model calls)
set -euo pipefail
cd "$(dirname "$0")/.."
export ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
exec uv run python -m odie.blocks_eval "$@"
