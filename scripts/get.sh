#!/usr/bin/env bash
# Odie's one-line install, for a Mac that doesn't have the code yet:
#   curl -fsSL https://raw.githubusercontent.com/sagarmainkar/odie/main/scripts/get.sh | bash
# It checks the Mac, installs the tools Odie needs with Homebrew when they're missing (never Homebrew itself: that
# asks for the Mac's password), fetches the code into a scratch folder, and hands over to scripts/install.sh, which
# puts Odie's own copy in ~/.odie/app at the newest release, builds it and starts the service. Then it opens setup.
# Running it again updates the install; data in ~/.odie (chats, settings, keys) carries over.
# Settings: everything scripts/install.sh reads (ODIE_HOME, ODIE_PORT, ODIE_REPO, ODIE_BRANCH, …), and ODIE_OPEN=off to
# not open the browser at the end.
# Everything sits in main(), called on the last line, so a download cut short runs nothing.
set -euo pipefail

REPO_URL="https://github.com/sagarmainkar/odie.git"
MIN_MACOS=14
MIN_NODE=20

say() { printf '%s\n' "$*"; }
stop() { printf '%s\n' "$*" >&2; exit 1; }

# Whether this computer can run Odie: a Mac with Apple Silicon on macOS 14 or newer. Linux runs Odie from a terminal,
# without this installer. A MacBook Air M2 on macOS 15.2 -> goes on; an Intel Mac or macOS 13 -> stops with why.
check_computer() {
  if [ "$(uname -s)" != "Darwin" ]; then
    stop "This installer is for macOS. On Linux, see: https://github.com/sagarmainkar/odie#mac-first-linux-today-more-welcome"
  fi
  if [ "$(uname -m)" != "arm64" ]; then
    stop "Odie needs a Mac with Apple Silicon (M1 or newer)."
  fi
  local major
  major="$(sw_vers -productVersion | cut -d. -f1)"
  if [ "$major" -lt "$MIN_MACOS" ]; then
    stop "Odie needs macOS $MIN_MACOS or newer (this Mac has $(sw_vers -productVersion))."
  fi
}

# Node's major version, or 0 when Node isn't there: "v22.11.0" -> 22.
node_major() {
  if ! command -v node >/dev/null; then
    echo 0
    return
  fi
  node -v | sed 's/^v//' | cut -d. -f1
}

# The tools Odie needs that are missing: git, uv and Node 20+. Git counts as missing when only Apple's stub is there
# (git --version fails until the Command Line Tools are installed). An old Node is not "missing": installing a second
# one beside it would confuse things, so that one stops with what to do.
# Everything there -> ""; no uv and no Node -> "uv node"; Node 18 -> stops ("brew upgrade node").
missing_tools() {
  local missing=""
  if ! git --version >/dev/null 2>&1; then
    missing="$missing git"
  fi
  if ! command -v uv >/dev/null; then
    missing="$missing uv"
  fi
  local node
  node="$(node_major)"
  if [ "$node" -eq 0 ]; then
    missing="$missing node"
  elif [ "$node" -lt "$MIN_NODE" ]; then
    stop "Odie needs Node $MIN_NODE or newer (this Mac has $(node -v)). Update it (brew upgrade node), then run this again."
  fi
  echo "$missing"
}

install_tools() {
  local missing
  missing="$(missing_tools)"
  if [ -z "$missing" ]; then
    return
  fi
  if ! command -v brew >/dev/null; then
    say "Odie needs:$missing."
    say "Install Homebrew first (https://brew.sh), then run this again:"
    stop '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  fi
  say "Installing with Homebrew:$missing…"
  # shellcheck disable=SC2086  # one word per tool
  brew install $missing </dev/null
}

main() {
  # Homebrew's tools, for a shell that hasn't put them on its PATH yet.
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
  check_computer
  install_tools

  local scratch
  scratch="$(mktemp -d)"
  # The folder's name goes into the trap now: by the time it runs, main's local variables are gone.
  trap "rm -rf '$scratch'" EXIT
  local repo="${ODIE_REPO:-$REPO_URL}"
  say "Fetching Odie…"
  git clone -q --depth 1 "$repo" "$scratch/odie"

  # Input from /dev/null: with curl | bash, this script itself is on stdin.
  ODIE_REPO="$repo" bash "$scratch/odie/scripts/install.sh" </dev/null

  local bin_dir="${ODIE_BIN_DIR:-$HOME/.local/bin}"
  if [ "${ODIE_OPEN:-on}" != "off" ]; then
    say "Opening setup in your browser…"
    "$bin_dir/odie" open || say "Open http://localhost:${ODIE_PORT:-8000} in your browser."
  fi
}

main "$@"
