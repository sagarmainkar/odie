# Security

Odie runs on your computer and holds your mail, notes and memory. This is how it keeps them to itself.

## Who can reach it

- The server listens on `127.0.0.1` only. From outside the Mac it is reachable through your own Tailscale
  network over HTTPS, and nowhere else.
- Every browser must **pair** with a one-time code (`odie pair`, valid once, ten minutes). A recovery passcode is
  shown once. Unpaired browsers see only the pairing screen; a device can be removed in Settings.
- Pairing can be turned off (`ODIE_PAIRING=off`). Then any program on the Mac that can reach the port can use Odie.
  Keep pairing on unless the Mac is only yours and you have a reason.
- Two checks run before any route, pairing on or off (`odie/app/origin.py`). The name a request gives in `Host` must
  be one Odie answers to: an IP address, `localhost`, a `.local` or `.ts.net` name, the phone address, or a name in
  `ODIE_HOSTS` in `~/.odie/.env`; anything else gets 421. That is what stops DNS rebinding, where an attacker's name is pointed at your
  own computer so their page counts as Odie's. And a browser request that changes something (a POST, an upload, a
  WebSocket) must come from Odie's own page: an `Origin` naming another site gets 403, so a page you happen to have
  open can't act as you even when pairing is off.

## What it may do without asking

- **Reads** (notes, mail, calendar, the web, prices) run on their own.
- **Writes ask first.** Sending mail, trashing, invitations, creating or changing events, running a shell command,
  installing a skill, acting on a signed-in site, saving a *Watch for* entry (a standing instruction the background
  watch follows every 30 minutes), and every connected app's tools: each pauses the turn with a card that shows the
  exact arguments (the command verbatim, the mail body, the event) and runs only on your tap. Cards expire after
  24 hours. "Run it, and allow commands for 30 min" is a choice you make per chat, and one tap approves one card.
- A connected app's tool runs without a tap only when you turn on "Reading doesn't need a tap" for that app *and*
  the tool's name says it reads (find, get, list, search, fetch). A server's own `readOnlyHint` frees nothing: it is
  the server's word about itself.
- **Once a tool in a chat has read your mail, notes, memory or messages** (or a page you're signed in to), a web
  search, a fetch, opening another site, a picture or clip search and a cloud voice ask first, with a card naming what
  the chat read. The words a model picks for a search can carry what it just read. Memory Odie already had in mind
  for the message (the notes it prefetches) doesn't count as a read, and other tools that reach the web (research,
  markets, a podcast or video) aren't in this list.
- The background watch stays off the web once a check has read mail or events; the one exception is an address you
  wrote in a Watch for entry yourself.
- The card also tells you when Odie read mail from someone just before asking to act, so a message can't quietly
  turn into an action.
- Every tool call is written to the audit log in `~/.odie/data`.

## Shell commands

`run_shell` runs as you, in your home folder (or a folder under it), with a time and output cap. Nothing runs
until you've read the command on the card.

"Allow for 30 min" lets the rest of a chat's commands run without a card, except the ones that must always ask
(`odie/agent/shell_grant.py`): reading secrets, deleting or stopping things, sending data out (including an address
built from other text), writing outside `/tmp`, the workspace and the vault, running text as commands (`| sh`,
`base64 -d`, `eval`), installing software, setting something to run at login, and reaching hidden files by a pattern.
The pass reads the command's text, with spelling tricks squeezed out; it is a list of the ways a command hides what it
does, not a proof. A script the chat wrote to the workspace and then runs is its own code, which the pass can't read:
if that worries you, don't use the pass. It never covers a new chat.

Adding an MCP server is running a program. The API refuses a spec that is nothing but a way to run text, a shell as the
command, an interpreter given code on its command line, an env that hooks code into the program, before it runs it
even to list its tools; a spec that names a real server (`npx`, `uvx`, `python -m`) runs that server's code, as it
must.

## The browser

Odie drives the Chrome, Edge, Chromium or Brave already on the computer, in a profile of its own, never yours.
It reaches public addresses only (no local network, no private ranges). Signing in to a site is a separate,
explicit step with its own card, and typing into a signed-in site asks each time.

## Updating

`odie update` and the app's button move Odie's own copy to the newest release tag (or `origin/<branch>`). The app's
button installs exactly the commit its check showed you: if the newest moved in between, nothing installs and it
asks you to check again. Commits and tags are not signed yet, so an upstream compromise would still reach an install
that updates; the one-line installer fetches `scripts/get.sh` from `main` over HTTPS the same way.

## Keys and data

- Keys are `NAME=value` lines in `~/.odie/.env` (owner-only). They're never written to logs or sent anywhere but
  their own provider.
- `~/.odie` is created owner-only. Back it up; delete it to erase everything.
- Which choices send data out of the computer is shown in Settings → Brain and in the table in the README.

## Reporting a problem

Use GitHub's private vulnerability reporting on this repository (Security → Report a vulnerability). Say what
you found and how to see it; you'll get a reply and a fix as quickly as one person can manage.
