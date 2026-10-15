#!/usr/bin/env bash
# A test run beside the real install: its own home (~/odie-runs/<name>), nothing from any other, started like
# scripts/start.sh starts Odie. A new name is a brand-new install; a name used before opens that run again.
#   scripts/fresh.sh glm-test        the run named glm-test (new, or that one again)
#   scripts/fresh.sh                 a new run named by the date and time
# For the real install at ~/.odie, use scripts/start.sh.
set -euo pipefail
NAME="${1:-$(date +%Y%m%d-%H%M)}"
RUNS="${ODIE_RUNS:-$HOME/odie-runs}"
mkdir -p "$RUNS"
ODIE_HOME="$RUNS/$NAME" exec "$(dirname "$0")/start.sh"
