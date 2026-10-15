#!/usr/bin/env bash
# One-time: give Odie an HTTPS address on your Tailscale network (your devices only). Persists across reboots.
# Odie finds the address by itself at its next start (odie restart); the phone opens it, then Add to Home Screen.
#   scripts/serve-tailscale.sh            (Odie on port 8000)
#   ODIE_PORT=8001 scripts/serve-tailscale.sh
set -euo pipefail
PORT="${ODIE_PORT:-8000}"
tailscale serve --bg --https=443 "http://127.0.0.1:${PORT}"
tailscale serve status
NAME=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
echo
echo "On the phone (Tailscale on): open https://${NAME}, then Share > Add to Home Screen."
echo "Restart Odie once (odie restart) so it shows this address in Settings and setup."
