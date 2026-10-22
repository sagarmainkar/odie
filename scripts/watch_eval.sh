#!/usr/bin/env bash
# How well the watch judges mail: made-up mails (evals/watch/cases and inboxes) through the real watch turn, on a
# throwaway home. Only the provider's API key is read from Odie's .env (~/.odie, or ODIE_HOME); nothing is written
# there. Results: evals/watch/<date>-<provider>-<model>.json and .md.
#   scripts/watch_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
#   scripts/watch_eval.sh anthropic/claude-sonnet-5-5 invite-from-a-person     (one case by id)
set -euo pipefail
cd "$(dirname "$0")/.."
export ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
exec uv run python -m odie.watch_eval "$@"
