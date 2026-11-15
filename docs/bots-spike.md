# Bots: the spike (November 2026)

An experiment on the branch `bots-spike`, built on the Workers spike (`workers-spike`, with main merged in) and
switched on with the same `ODIE_WORKERS=1`. It gives Odie a team of named bots, each with its own model, prompt and
powers, led by a chief that works like Grok's team of agents: one lead splits a request among specialists, runs them
side by side, weighs what they say against each other and gives one answer.

## How it flows

```
you: "@chief should I buy X or Y?"            (or Odie decides: ask_bot(bot="chief", …))
  -> the chat calls ask_bot -> a chief job (a Worker, kind "bot", on the chief's model and powers)
  -> chief: list_bots, make_bot for missing specialists (researcher, numbers, skeptic, …)
  -> chief: ask_bots([{bot, brief}, …])  -> up to 4 teammate jobs run at once (parent_id = the chief's job)
  -> each teammate reports to the chief, never to the chat
  -> chief weighs them and reports once -> one message in your chat, with a push
```

- A bot is a row in `bots`: name, role, prompt, model (none = the chat's), powers, who made it, and whether you
  edited it. Its folder `<workspace>/bots/<name>/` outlives its jobs; `notes.md` there is its memory.
- Powers: `web` (search, fetch), `files` (its folder; every bot has read_file/write_file for its notes), `shell` (the
  pass's always-ask rules refused, as for every Worker), `browser` (Odie's signed-in browser).
- Only the chief has the team tools. A specialist can't make bots or ask others, so a run is at most two levels deep.
- The chief makes bots; you change any bot's role, prompt, powers and model in Settings → Bots. A bot you changed is
  yours: the chief can use it but no longer change it. The chief can't be deleted.
- `@name …` at the start of a message adds a one-line nudge so the chat calls ask_bot (`odie.workers.nudge`).
- A bot on a schedule: "every morning, @researcher …" gives ask_bot `every_minutes` (and `until`, `notify`,
  `condition`, as for a Workers reporter). Each run starts fresh, told its last report, with 15 minutes; it stops
  after 24 hours unless told otherwise, 7 days at most.
- Today: a chief's row says how many teammates are done ("2 of 3 teammates done"); More shows each teammate's
  report.

## Watching the team (like Grok)

Under Odie's "Sent it to @chief" sits a live team card (`components/TeamCard.tsx`, `odie/workers/progress.py`,
`GET /api/jobs/{id}/team`): the chief and each teammate with its model, time, steps and what it is doing right now
("searching …", "reading zigwheels.com", "waiting for 4 bots", "waiting for your tap"). The app asks every 2.5 s while
the chief works; afterwards each line shows its answer's first line and opens to the whole report. Live on 15 Nov:
chief + 4 teammates, 7.5 minutes, one tap.

## The browser, and what waits for you

A bot with the browser runs with the turn a chat would have: its brief counts as your words (sites it names may be
opened), the browser is signed in where you are, and Odie's saved logins fill in by themselves. What changes is who is
there to ask:

- A step the chat would put a card in front of (a click that may order, pay, book or send; typing on a signed-in site;
  leaving a site whose signed-in pages it read) makes the job wait. Today shows the question with Allow / Deny, the
  chat gets a line and the phone a push. No answer in 9 minutes is a no (the browser closes a page after 10 idle
  minutes).
- A sign-in page (or a saved login that needs a code) makes the bot call `browser_sign_in`; Today shows Sign in (the
  live view of the bot's own tab), Done and Skip.
- Only the app's buttons answer (`POST /api/jobs/asks/{id}`). No tool, no chat message and not the terminal's key can:
  a model, the chief, or an agent at the terminal can never say yes for you.
- Private goes with the words (`odie/workers/privacy.py`). A bot asked from a chat that read a signed-in page or your
  mail starts private; so does a teammate the chief asks after another teammate read one; so does a scheduled bot's
  next run, and every later job of a bot whose notes may hold it. A private bot's searches and other sites wait for
  your tap. Back out: a bot's report makes the chief or chat it reaches private, and so does `jobs_status` showing it.
  The welcome leaves a private report's text out. A plain Worker (`start_job`) has no tap, so a private chat can't
  start one.
- A bot's brief is never "your words": in a chat, a site you name may be opened without a tap; a brief is written by a
  model that may have read a page, so naming a site in it opens nothing private.
- One tap, not one per step: a job that starts private (its chat looked at your memory, say) asks once, at the start
  ("Let chief work on 'Goa' with the web? This chat read your memory…"). Allow clears those marks for the job and its
  teammates; anything new they read (a signed-in page) still asks. Deny: every step asks. Seen live: before this, a
  chat that had looked at memory once made every bot ask before every search.
- The questions rely on pairing: with pairing on (as on this Mac), only a paired browser answers, never the terminal's
  key. With `ODIE_PAIRING=off`, any program on the Mac can call the route, the same as the chat's own approvals.
- The watchdog leaves a job alone while it waits on you or on its teammates; a restart expires every open question.

## What is built

- `odie/workers/bots.py`: the store (make, edit, delete, the chief made on start), names, powers, models.
- `odie/workers/team.py`: a bot's kind, instruction and tools; the chief's `list_bots`, `make_bot`, `ask_bots`;
  `browser_sign_in` for bots; teammates run under their own limit of 4 (not the Router's 3 slots, so a chief waiting
  in a slot can't starve them).
- `odie/workers/asks.py`: the questions (`job_asks`), the wait, the answer, expiry.
- `odie/workers/worker.py`: bots run on their own model; the guard waits for a tap where the chat would ask; a
  teammate's run tells nobody; a signed-in read passes privacy on.
- `odie/workers/tools.py`: the chat's `ask_bot`. `router.start_bot`, recovery that closes teammates.
- Routes: `/api/bots` (GET, POST, PUT, DELETE), `/api/jobs/asks/{id}`, and `asks` in `/api/jobs`.
- Web: Settings → Bots (`components/BotsSection.tsx`, `bots.ts`), questions on Today's Jobs (`components/Jobs.tsx`).
- Tests: `tests/test_bots.py` (the store, tools by power, the chief's run with a team through the real ADK, teammates
  side by side, a tap that pauses a real ADK run, no and silence, restart, the watchdog, privacy, routes, the terminal).

## Live findings (15 November, DeepSeek V4.1 Flash for every bot, throwaway home)

| Check | Result |
|---|---|
| "@chief used Classic 350 (2022) or new CB350 in Bangalore?" | The chat called ask_bot at once. The chief made researcher, numbers and skeptic, asked all three side by side (37 + 30 + 16 calls), then caught a disagreement and asked numbers again, which found its own double-counted insurance. One answer in the chat after 5 minutes: "a near dead heat on money, buy the new CB350 unless the used Classic is ≤ ₹1.70L", with who found what, and answer.md and notes.md attached. |
| The skeptic | Did its job: it said the brief anchored on an unrealistically low used price, and that new CB350 and new Classic cost the same on-road. The chief's answer took both. |
| Teammates and the chat | Only the chief's message reached the chat; Today shows the chief's job with "4 teammates", not five rows. |
| A bot with the browser (`@shopper`, made in Settings) | Opened example.com, read it, reported. 4 calls. |
| A question on Today | Allow and Deny answer it through `/api/jobs/asks/{id}`; the card goes. The tap through a paused real ADK run is in the tests (a signed-in tap needs a real account, not tried on the throwaway). |
| Settings → Bots | The team, each with role, instructions, model (the chat's or any listed one), powers; Save makes it yours. |

**A bug found on the way (from the Workers spike, fixed here):** every `useLive` opened its own `/api/events`
stream. With Today's Jobs section the page held six, Chrome's limit per host over plain HTTP, and every tap and fetch
after that waited forever (an Allow tap went through only when the tab closed). The app now shares one stream
(`shareLive` in `web/src/live.ts`). Main has five components that listen (App, Today, Chat, TrackingSection,
ReminderCurtain), so it sits close to the same limit: worth taking to main on its own.


## Since the first version (15 November, evening and night)

Built on Fable's design (`docs/bots-design.md`) and the OpenBot comparison:

- **Bots you talk to.** Each bot has its own conversations (`odie/workers/convs.py`). A message is answered by one of
  the bot's jobs whose brief carries the conversation so far; the reply lands as the bot's message, with a push. The
  Bots list (Odie pinned, the team with furry creatures in colour, live lines, a chip when a bot waits on you), a
  bot's chat (team card while it works, a pill above each answer with what it took, questions with their buttons), a
  drawer to switch bot and conversation (a swipe from the left edge on a phone, pinned open on a Mac), and a Bots card
  on Today. "@chief …" in Odie's chat also lands in the chief's history.
- **Starter team.** chief, researcher, checker, contrarian, made once.
- **Routines** (`odie/workers/routines.py`): a bot that runs by itself, daily or on chosen weekdays at a time, or every
  few hours, for good until paused. Each has its own conversation; each run sees the earlier ones and says what changed.
  Set them in a bot's details or from Odie's chat ("every weekday at 9:15, @markets …": make_routine).
- **Details** for each bot: role, instructions, model, powers, Runs by itself, Recent work, memory notes, Shuffle look.
- **Notes & photos power**: search the user's notes, photos and videos by meaning. Reading them marks the run, so its
  web steps ask, as Odie's chat does; a bot with no web or browser never asks.
- **Odie's visual blocks** in a bot's answers (charts, tables, figures, badges), as in Odie's own replies.
- **Browser like OpenBot's**: Watch a bot's page live (nothing changes for the bot), Take control (its next browser step
  waits, checked live), back, forward, reload, address; Hand back. A code or PIN a bot needs is typed by the user
  straight into the page (`ask_user_to_type`, `engine.type_secret`): kept, logged and shown nowhere. A bot at a bot
  check hands it to the user. Watch also works on Odie's own browser in the main chat.
- **Privacy, one tap**: a job that starts private (its chat looked at your memory or a signed-in page) asks once at the
  start; Allow covers the bot and its teammates; anything new they read still asks.

## Not built

- Workflows saved as chains (researcher → writer → reviewer): you chose the lead-bot design first.
- Teaching a bot by recording yourself (OpenBot's Learning): parked by you.
- A per-bot browser profile: every bot shares Odie's one signed-in profile, each in its own tab.
- Nested teams: a specialist can't ask others.

## Trying it beside the live Odie

```sh
cd <the worktree of this branch>
export ODIE_HOME=$HOME/odie-bots-home ODIE_PORT=8832 ODIE_SCHEDULER=0 ODIE_PAIRING=off ODIE_WORKERS=1 ODIE_VOICE=off
export ODIE_HOSTS=127.0.0.1:8832,localhost:8832
mkdir -p $ODIE_HOME
uv run python -c "from odie import config; from odie.store.db import Store; s=Store(config.settings.db_path); s.init_schema(); s.set_setting('model.chat', {'provider':'ollama','model':'deepseek-v4.1-flash:1017-cloud'})"
(cd web && npm ci && npm run build)
uv run uvicorn odie.app.main:create_app --factory --host 127.0.0.1 --port 8832
```

Open http://127.0.0.1:8832 on the Mac and try "@chief …" with something that needs several sides. Settings → Bots
shows the team. `rm -rf ~/odie-bots-home` when done.
