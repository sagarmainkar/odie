# Security

Odie runs on your computer and holds your mail, notes and memory. This is how it keeps them to itself.

## Who can reach it

- The server listens on `127.0.0.1` only. From outside the Mac it is reachable through your own Tailscale
  network over HTTPS, and nowhere else.
- Every browser must **pair** with a one-time code (`odie pair`, valid once, ten minutes). A recovery passcode is
  shown once. Unpaired browsers see only the pairing screen; a device can be removed in Settings.
- Pairing can be turned off (`ODIE_PAIRING=off`). Then anything that can reach the port can use Odie: any program
  on the Mac, and possibly a malicious web page in a browser on it (the server doesn't check where a request
  comes from). Keep pairing on unless the Mac is only yours and you have a reason.

## What it may do without asking

- **Reads** (notes, mail, calendar, the web, prices) run on their own.
- **Writes ask first.** Sending mail, trashing, invitations, creating or changing events, running a shell command,
  installing a skill, acting on a signed-in site, and any app tool its server doesn't mark read-only: each pauses
  the turn with a card that shows the exact arguments (the command verbatim, the mail body, the event) and runs
  only on your tap. Cards expire after 24 hours. "Run it, and allow commands for 30 min" is a choice you make per chat.
- The card also tells you when Odie read mail from someone just before asking to act, so a message can't quietly
  turn into an action.
- Every tool call is written to the audit log in `~/.odie/data`.

## Shell commands

`run_shell` runs as you, in your home folder (or a folder under it), with a time and output cap. Nothing runs
until you've read the command on the card.

## The browser

Odie drives the Chrome, Edge, Chromium or Brave already on the computer, in a profile of its own, never yours.
It reaches public addresses only (no local network, no private ranges). Signing in to a site is a separate,
explicit step with its own card, and typing into a signed-in site asks each time.

## Keys and data

- Keys are `NAME=value` lines in `~/.odie/.env` (owner-only). They're never written to logs or sent anywhere but
  their own provider.
- `~/.odie` is created owner-only. Back it up; delete it to erase everything.
- Which choices send data out of the computer is shown in Settings → Brain and in the table in the README.

## Reporting a problem

Use GitHub's private vulnerability reporting on this repository (Security → Report a vulnerability). Say what
you found and how to see it; you'll get a reply and a fix as quickly as one person can manage.
