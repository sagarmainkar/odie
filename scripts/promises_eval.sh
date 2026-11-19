#!/usr/bin/env bash
# How well Odie reads promises in chat: made-up turns (evals/promises/cases) through the real after-turn read, on a
# throwaway home. The read has no tools, so nothing of this Mac is reachable; no key is copied from Odie's .env.
# Results: evals/promises/<date>-<provider>-<model>.json.
#   scripts/promises_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m odie.promises_eval "$@"
