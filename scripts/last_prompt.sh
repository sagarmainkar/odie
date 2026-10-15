#!/usr/bin/env bash
# Show the exact request Odie last sent to the model. See scripts/last_prompt.py for options.
exec python3 "$(dirname "$0")/last_prompt.py" "$@"
