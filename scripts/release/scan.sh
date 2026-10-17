#!/usr/bin/env bash
# Reads a folder for anything personal before it goes public. Two lists:
#   - private words: names, host names, private projects. They live OUTSIDE the repo, one regex per line, in
#     $ODIE_PRIVATE_WORDS (default ~/.config/odie-release/private-words.txt), so this script can't leak them itself.
#     In CI the file comes from a repository secret.
#   - key shapes and personal shapes (phone numbers, Gmail addresses), below: generic, safe to publish.
# Every hit is listed with its file and line; any hit that isn't a known test placeholder stops the release.
#   scripts/release/scan.sh /tmp/odie-public                  (the private words file must exist)
#   scripts/release/scan.sh /tmp/odie-public --keys-only      (no private words: a fork's PR in CI)
set -uo pipefail
DEST="${1:?the folder to scan}"
MODE="${2:-}"
WORDS="${ODIE_PRIVATE_WORDS:-$HOME/.config/odie-release/private-words.txt}"

PRIVATE=()
if [ "$MODE" != "--keys-only" ]; then
  if [ ! -s "$WORDS" ]; then
    echo "No private words at $WORDS: the scan can't check for personal data. Create it (one regex per line),"
    echo "or pass --keys-only to check key shapes alone."
    exit 2
  fi
  while IFS= read -r w; do
    [[ -z "$w" || "$w" == \#* ]] && continue
    PRIVATE+=("$w")
  done < "$WORDS"
fi

# Key shapes: a hit is fine only when it is one of the made-up placeholders the tests use.
KEYS='(sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{20,}|tvly-[A-Za-z0-9_-]{10,}|AIza[A-Za-z0-9_-]{20,}|lsv2_[a-z]{2}_[A-Za-z0-9]{10,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[bp]-[A-Za-z0-9-]{10,})'
PLACEHOLDERS='(sk-secretvalue|sk-specific|sk-completion|sk-abcdefgh|tvly-dev-Ab|AIzaSyAbCd|AIzaSyA-bc|sk-ant-api03-Ab)'
# Shapes that are personal whoever the owner is: a real-looking phone number, a Gmail address.
SHAPES=('\+91[ -]?[0-9]{5}[ -]?[0-9]{5}' '[A-Za-z0-9._%+-]+@gmail\.com')
# Lines that are fine: the licence's copyright line, .gitignore (it names private files to keep them out), the
# repository's own address (on github.com, and its files on raw.githubusercontent.com), and the tests' made-up contacts.
ALLOWED='(^\./LICENSE:[0-9]+:Copyright|^\./\.gitignore:|github\.com/[A-Za-z0-9-]+/odie|raw\.githubusercontent\.com/[A-Za-z0-9-]+/odie/|asha@gmail\.com|someone@gmail\.com|\+91 98765 43210)'

cd "$DEST"
hits=0
# Font files (.woff2) are binary glyph data, not text a person wrote. A short private word can match some bytes
# in them by chance (KaTeX's fonts did, 16 Oct 2026), so the word scan skips them. The map's place names
# (odie/video/kit/geo, Natural Earth, public domain) are skipped too: a town can share its name with a person
# (a town in Madhya Pradesh did, 17 Oct 2026).
report() {  # report <label> <grep -E pattern>: lists each line that matches and isn't allowed
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    echo "$1  $line"; hits=$((hits + 1))
  done < <(grep -rniE --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git --exclude-dir=geo --exclude='*.woff2' "$2" . 2>/dev/null | grep -vE "$ALLOWED" | cut -c1-160)
}
for p in "${PRIVATE[@]+"${PRIVATE[@]}"}"; do report "PERSONAL" "$p"; done
for p in "${SHAPES[@]}"; do report "PERSONAL" "$p"; done
while IFS= read -r line; do
  [ -z "$line" ] && continue
  if echo "$line" | grep -qE "$PLACEHOLDERS"; then continue; fi
  echo "KEY       $line"; hits=$((hits + 1))
done < <(grep -rnoE --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git "$KEYS" . 2>/dev/null | cut -c1-160)

files=$(find . -type f -not -path './.git/*' -not -path '*/node_modules/*' -not -path './.venv/*' | wc -l | tr -d ' ')
if [ $hits -eq 0 ]; then
  if [ "$MODE" = "--keys-only" ]; then
    echo "Clean: no keys in $files files (private words not checked)."
  else
    echo "Clean: nothing personal and no keys in $files files (${#PRIVATE[@]} private words checked)."
  fi
else
  echo "$hits hit(s): fix them in the repo (or add a placeholder here when it's a test value), then scan again."
  exit 1
fi
