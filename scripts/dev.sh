#!/usr/bin/env bash
# Run Odie's API + PWA on 127.0.0.1:8000 (reach it through tailscale serve, see serve-tailscale.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:$PATH"
exec uv run uvicorn odie.app.main:create_app --factory --host 127.0.0.1 --port 8000 --log-level info
