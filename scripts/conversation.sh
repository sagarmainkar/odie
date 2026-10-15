#!/usr/bin/env bash
# Save an install's conversations as Markdown (see conversation.py).
cd "$(dirname "$0")/.." && exec uv run --quiet python scripts/conversation.py "$@"
