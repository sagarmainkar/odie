#!/usr/bin/env bash
# Replays a test conversation of yours (evals/chats/*.turns.json) through another model, every turn in ONE chat, on a
# throwaway home, so the chats can be compared (evals/chats/*.md; the app's #sample screen shows only evals/sample). Read from Odie's folder
# (~/.odie, or ODIE_HOME), never written: the provider's key and TAVILY_API_KEY from its .env, SOUL.md and the user's
# and assistant's names. Results: evals/chats/<date>-<provider>-<model>.json and .md. Scoring uses the web app's own
# parsers, so web/ needs its packages (npm ci).
#   scripts/chat_replay.sh anthropic/claude-sonnet-5-5
#   scripts/chat_replay.sh anthropic/claude-opus-5-5 --thinking   the chat's "think longer" toggle on (the app's default)
#   scripts/chat_replay.sh --import-session chat-2026-10-11 --label lmstudio/gemma-4-26b-a4b-it-qat   (a live chat, read only)
#   scripts/chat_replay.sh --rescore            score the saved chats again after a parser change (no model calls)
set -euo pipefail
cd "$(dirname "$0")/.."
export ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
exec uv run python -m odie.chat_replay "$@"
