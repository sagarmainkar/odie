# Contributing to Odie

Thanks for helping. Odie is a small project with one maintainer, so this page says exactly what a good pull
request looks like and what happens to it.

## Before you start

- **A bug fix or a small improvement:** open the pull request directly.
- **A new feature or a bigger change:** open an issue first and describe what you want to change and why. Odie
  stays small on purpose. Agreeing on the idea first saves you writing code that won't be merged.
- **A security problem:** don't open an issue. Use the private reporting described in [SECURITY.md](SECURITY.md).

## Setting up

Odie runs on macOS (Apple silicon is best). You need `git`, [`uv`](https://docs.astral.sh/uv/) and Node 20+.

```bash
git clone https://github.com/<you>/odie.git && cd odie     # your fork
uv sync
cd web && npm ci && cd ..
scripts/start.sh        # this folder's code in the terminal, on port 8001 with its own home in ~/odie-dev
```

`scripts/start.sh` never touches an installed Odie (`~/.odie`, port 8000), so you can work on Odie while using it.

## The checks

Run these before you open a pull request. CI runs the same ones, and a pull request is merged only when they pass.

```bash
uv run pytest -q                 # the Python tests (about 5 minutes)
cd web
npm run lint                     # warnings are fine; errors are not
npx vitest run                   # the web tests
npm run build                    # type check and build
```

The tests never call a real model, never use the network and never touch `~/.odie`: every test runs in a temporary
home with no keys. Keep it that way. A test that needs a model uses a scripted one; a test that needs an AI provider's
SDK uses the real SDK class over a mock HTTP transport.

For a change you can see, `scripts/screens.sh` photographs every screen at phone width, light and dark, on a
throwaway Odie (it never touches yours), and lists anything wider than the phone or too small to tap. Put the shots
that show your change in the pull request.

There is also a live check against a real model, which you run by hand and never in CI:

```bash
ODIE_LIVE=1 ODIE_LIVE_MODEL=ollama/glm-5.3-flash:cloud uv run pytest tests/integration -s
```

It runs five chat turns on a throwaway home with the model you name, reading only that provider's key from
`~/.odie/.env`.

## Writing code here

- **Code a person can follow on the first read.** A few plain named lines over one clever line. No nested
  `getattr(getattr(...))`, no conditional values packed into a call's arguments, no stacked `x or y or "..."`
  fallbacks, no walrus tricks in conditions.
- **Every decision function gets a comment with a worked example.** Predicates, guards and checks
  (`is_*`, `should_*`, `needs_*`) say in words what they decide, then show input → outcome. For example:
  "`ls ~/Downloads` with a pass → runs, no card; `rm old.txt` with a pass → card anyway".
- **Made-up data only** in tests, fixtures and examples: the test person is "Asha", addresses are `example.com`.
  Never real names, real e-mail addresses, real paths from your machine or real keys.
- **Writes ask first.** Anything that sends, deletes, buys or changes something outside Odie must go through an
  approval card. Reads never ask.
- **The system prompt stays stable.** If you change a prompt or the tool list, regenerate the golden files
  (`uv run python -m tests.golden_render --write`) and say why in the pull request.

## Adding things

### A skill (no code)

A skill is a folder with a `SKILL.md`: instructions the model loads when they fit, plus the tools it may use. Put
your own in `~/.odie/skills/`. A built-in one lives in `odie/skills/`.

```markdown
---
name: weekly-review
description: A Sunday review of the week from my notes and calendar: wins, open loops, next week's three.
metadata:
  adk_additional_tools: [search_notes, read_note, calendar_list_events]
---
# Weekly review

Ask for the week's notes with `search_notes`, read the ones that matter, list next week's events, then write
three short sections: Wins, Open loops, Next week's three. Draw the open loops as a checklist block.
```

- `name` and `description` are what the model sees in its skill list, so the description says *when* to use it.
- `adk_additional_tools` names tools that switch on with the skill: Odie's own or a connected app's.
- Everything under the frontmatter is the instruction: what to call, in which order, and how to answer.

### An app (an MCP server)

Add it to `~/.odie/mcp.json` (see [the setup guide](docs/setup.md#5-connected-apps-mcp)). Odie turns it into a skill:
the server's title and description become the skill's, and its tools join when the skill loads. Tools the server
marks `readOnlyHint` run without a tap.

### A visual block (some code)

The model draws with blocks from `odie/blocks/catalog.json`, and the app draws them in `web/src/blocks/`. To add
one (the `heatmap` block is a good example to copy):

1. **Catalogue.** An entry in `odie/blocks/catalog.json`: `kind`, `for`, `use_when`, `fields`, and a small valid
   `example`. The whole catalogue sits in the system prompt, and `tests/test_blocks_catalog.py` keeps it under a
   token budget.
2. **Parser.** `web/src/blocks/parse/<kind>.ts`: a reader that returns the block or `here.drop("why")`. Accept the
   aliases models guess, cut long text, cap list lengths.
3. **Register.** The type in `Block` and the reader in `READERS` (`web/src/blocks/parse.ts`). Wide blocks also go in
   `WIDE_KINDS` (`parse/containers.ts`).
4. **Component.** `web/src/blocks/<Kind>.tsx` and a line in `DRAW` in `Blocks.tsx`. Use the theme's tokens
   (`var(--t-…)`, the `glass` classes) so it works in light and dark.
5. **Tests.** Parser cases, a render check with `renderToStaticMarkup`, and the golden prompts regenerated.

The gallery at `#blocks` in the app draws every catalogue example.

## Pull requests

1. **One change per pull request**, on a branch of your fork.
2. **Fill in the template:** what changed and why, how you tested it, and screenshots at phone width (about 390 px)
   in light and dark for anything you can see.
3. **CI runs the checks** on a macOS runner. On your first pull request, a maintainer has to approve the run first:
   that's GitHub's protection against code that misuses CI.

What happens next:

- The maintainer reads every line and tries the change on a throwaway install (never a real one).
- You'll get a merge, a request for changes with the reasons, or a polite no with the reason.
- Merged pull requests are squashed into one commit with a plain sentence as its message.
- Changes reach people with the next release (a tag like `v0.2.0`). Installs update to releases only.

## Licence

Odie is MIT licensed. By sending a pull request you agree that your contribution is licensed under the same
[MIT licence](LICENSE). There is nothing to sign.
