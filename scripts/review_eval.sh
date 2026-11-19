#!/usr/bin/env bash
# How well the evening review judges: made-up ledgers (evals/review/cases) through the real review, on a throwaway
# home. The review has no tools, so nothing of this Mac is reachable; no key is copied from Odie's .env.
# Results: evals/review/<date>-<provider>-<model>.json.
#   scripts/review_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python -m odie.review_eval "$@"
