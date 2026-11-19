#!/usr/bin/env bash
# How well Odie keeps loops: made-up cases (evals/loops/cases) through the real watch turn and stage 4, on a throwaway
# home, with a fake gh (evals/loops/fake_gh.py). Only the provider's API key is read from Odie's .env; nothing is
# written there. Results: evals/loops/<date>-<provider>-<model>.json.
#   scripts/loops_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
#   scripts/loops_eval.sh anthropic/claude-sonnet-5-5 fourteen-mails-one-pr     (one case by id)
set -euo pipefail
cd "$(dirname "$0")/.."
export ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
exec uv run python -m odie.loops_eval "$@"
