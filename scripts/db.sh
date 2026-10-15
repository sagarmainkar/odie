#!/usr/bin/env bash
# Browse Odie's two SQLite databases in a web page (Datasette). Read queries only; safe while the server runs.
#   scripts/db.sh            -> http://127.0.0.1:8001
set -euo pipefail
DATA="${ODIE_DATA_DIR:-$HOME/.odie/data}"
exec uvx datasette "$DATA/assistant.db" "$DATA/sessions.db" --setting sql_time_limit_ms 5000 --open "$@"
