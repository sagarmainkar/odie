#!/usr/bin/env bash
# Copies the chat replays (scripts/chat_replay.sh runs, still in their throwaway homes in the temp folder) into Odie's
# own folder (~/.odie, or ODIE_HOME) as chat threads, so they open from Chat → Threads. Only the conversation is copied
# (session, events, thread title, the media its replies made), never tasks, reminders, memories or settings. Each
# throwaway home is matched to its saved run in evals/chats by its replies, which names the thread.
# Stop Odie first: it refuses while the server answers. It backs up assistant.db and sessions.db beside the home
# (~/.odie-backups/before-replay-threads-<time>/) before writing, and prints how to restore them.
#   scripts/replay_to_threads.sh --all --dry-run     the plan, nothing written
#   odie stop; scripts/replay_to_threads.sh --all; odie start
#   scripts/replay_to_threads.sh /var/folders/…/T/odie-chat-replay-xxxx/home   just one
set -euo pipefail
cd "$(dirname "$0")/.."
export ODIE_HOME="${ODIE_HOME:-$HOME/.odie}"
unset ODIE_DATA_DIR ODIE_CONFIG_DIR  # the target is always ODIE_HOME's data folder, as with the odie command
exec uv run python -m odie.replay_threads "$@"
