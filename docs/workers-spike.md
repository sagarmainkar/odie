# Workers: the spike (November 2026)

An experiment on the branch `workers-spike`, switched on with `ODIE_WORKERS=1` and off by default. It tries the Worker
half of DeepSeek Harness's "Exploring Super-agent Design" (31 October 2026) inside Odie: a long job the user asks for
in chat runs in a background Worker of its own and reports back into the chat. Three questions it set out to answer,
and the answers so far:

1. **Can kinds that don't need the main model run on a small local model?** Yes for a reporter. Ollama's `lfm3`
   (1.7 GB) ran a Downloads-folder report in 5 clean tool calls and 13 seconds; Gemma 4 26B in LM Studio did a
   process-count report in 14 seconds and, on its second run, said what changed against the first. Loading a second
   LM Studio model beside the one already loaded failed for memory, so a kind's local model has to be the one that is
   already up (or on Ollama, which loads small models on demand).
2. **How are errors caught, and who starts a job again?** A watchdog in code reads the jobs store once a minute and
   fails a job that ran past its budget, made no call for 10 minutes, or hit the same refusal three times; a reporter
   that fails two runs in a row stops. The chat is told with "retry <id>". Starting again is the user's call, through
   `retry_job`. A restart of Odie tells each cut-off job in its chat and relaunches reporters on their kept schedule;
   checked live.
3. **How does data flow?** Chat -> `start_job` -> Router (code: row, folder, task) -> Worker (own session, the brief
   as its first message, every call to `job_actions`) -> `report` -> Router posts one message into the chat with a
   push. A reporter runs again every N minutes in a fresh session, told its last report. Nothing else crosses.

## What is built

- `odie/workers/tools.py`: `start_job(title, brief, every_minutes, until)`, `jobs_status`, `stop_job`, `retry_job`.
- `odie/workers/nudge.py`: a one-line reminder on messages that read like a job, after the context note.
- `odie/workers/router.py`: writes the row and folder, runs the Worker in its own task (3 at a time), repeats a
  reporter, fails on the watchdog's word, retries, recovers after a restart, stops everything at shutdown.
- `odie/workers/worker.py`: one ADK session per run with the kind's instruction and tools plus `report`; the guard
  on the shell (the pass's always-ask rules, refused with a line); the record of every call; the message to the chat.
- `odie/workers/kinds.py`: `task` (shell, `write_file`, `read_file`, web reads; 30 minutes, 80 calls) and `reporter`
  (the same tools, a shorter run, notes in its folder). A kind can run on its own model: setting
  `workers.model.<kind>` = `{"provider": "ollama", "model": "lfm3:latest"}`.
- `odie/workers/watchdog.py`: the verdicts above; `odie/workers/store.py` and `schema.sql`: `jobs` and `job_actions`.
- `odie/app/main.py`: the watchdog job every minute, recovery at startup, stop at shutdown, all behind the switch.

## Live findings (4 November, DeepSeek V4.1 Flash as the chat model, throwaway home)

| Job | Model | Calls | Refusals | Wall time |
|---|---|---|---|---|
| Fibonacci script, files through the shell | DeepSeek | 26 | 6 | 37 s |
| Mac health check | DeepSeek | 6 | 0 | 11 s |
| Primes script, with `write_file` | DeepSeek | 6 | 1 | 10 s |
| Primes script, no hint in the message | DeepSeek | 4 | 0 | 8 s |
| Disk and memory reporter, 2 runs | DeepSeek | 5 per run | 0 | 20 s per run |
| Downloads reporter | lfm3 on Ollama | 5 | 0 | 13 s |
| Processes reporter, 2 runs | Gemma 4 26B, LM Studio | 6 and 5 | 0 | 14 s per run |

- **Delegation.** With a soft nudge ("if this takes code to write and run… hand it to a Worker") DeepSeek still ran
  the coding request in the chat and raised a shell card. With a direct one ("This is a job for a Worker: call
  start_job now… Don't use run_shell here for it") the same message went to a Worker. "Every 5 minutes" alone was
  enough for the reporter. A question ("how is the market today?") gets no nudge.
- **Files.** Before `write_file`, every file went through the shell, where backticks in a docstring tripped "runs
  text as commands" six times. With `write_file` the same job needed 6 calls, then 4.
- **Reporters.** Each run is a fresh session told its last report; run 2 said "disk and swap identical to last run,
  RAM compressed harder" (DeepSeek) and "processes decreased from 730 to 635" (Gemma). Both kept notes in their
  folder without being asked twice.
- **Recovery.** The first restart found nothing to relaunch: shutdown had marked every row stopped. Fixed; the second
  restart logged "reporter launched again", waited for the kept `next_run_at`, ran, and finished on schedule.
- **Local models.** Gemma 12B could not load beside the 26B already in LM Studio ("insufficient system resources");
  the reporter failed twice and, before the fix, still "finished after 2 reports". Now two failed runs stop it.
  Gemma 26B called `ls -a` and `report` twice each (harmless; the second report overwrote the first with the same
  text). lfm3 made no such slip.
- **The chat remembers.** Asked for the same script again, the chat answered from the earlier report in its history
  ("Already done a few minutes ago, job-…"), and it called a second Downloads watch "(retry)" on its own.

## Round two (4 November, evening): the trimmed plan

Built after the decision to keep the chat and the clock as the only triggers (no Router model, no trigger queue):

- **One small model for the light kinds.** Settings → Brain shows "Small model for Workers" with a Chat / Workers
  switch; the pick is `model.workers`. With none, Odie asks Ollama once per process and takes `lfm3:latest` (else an
  `lfm2`) as its own pick, else the chat model. A reporter runs on it; a task job stays on the chat model.
- **Reporters speak by a rule.** `start_job(notify="always" | "change" | "condition", condition=…)`; `report` takes
  `state`, `met` and `done`. Code decides whether a run is told, as a tracker's check is judged; a quiet run is still
  on the record. `done` ends the reporter with "nothing left to watch". The old trackers are untouched for now.
- **Stuck jobs wait on Today.** A job that is blocked, failed, or failed by the watchdog gets a Needs-you card with
  Retry and Dismiss (`forget_job`).
- **Odie speaks first.** When the app opens or comes back after 3 hours or more away (`POST /api/chat/welcome`), one
  message in the chat: done, didn't finish, waiting on you, up next, with an `actions` block (Retry …, "What needs
  me?", "Show what you did"). Once per absence; nothing when there is nothing to say.
- **Today lists the jobs.** A Jobs section: running with Stop, ended with Retry, More opens the report and the log
  (`/api/jobs`, `/api/jobs/{id}`, stop and retry).
- Messages Odie posts on its own say what they are after its name: job, while you were away, tracker.

Live, on the throwaway with DeepSeek as the chat model and lfm3 picked by Odie:

| Check | Result |
|---|---|
| Change-only reporter on lfm3 (Downloads count) | Ran; report every 30 s until stopped at report (26 model calls): fixed, a Worker makes no model call after `report`. It called the first run "dropped" and `done`: a reporter now treats "dropped" as a quiet run; `done` from a small model is still trusted. |
| Blocked job (Zerodha holdings, no token) | DeepSeek's Worker searched env, profiles and files, tested the API, reported blocked with a clear ask and handed over the script it wrote; a Needs-you card appeared with Retry and Dismiss. |
| Welcome after a simulated 5.6 h away | Posted into the chat with the three buttons; a second call posted nothing. |
| Today | Needs-you card and the Jobs section render (screenshots under `.playwright-mcp/workers/`). |
| Chat | The welcome renders with its buttons after a reload. A hash-only switch from Today to Chat in the headless browser showed the chat's earlier state; worth watching on the phone. |

## Not built, by choice or not yet

- The mail kind (may send, no shell, recipients fixed at start, only from the user's own chat turn). Decided: the
  Gmail MCP send tool; parked until built.
- Trackers moved onto reporters, and the watch as a job on the small model (after the watch eval compares lfm3 with
  DeepSeek).
- The watchdog was not provoked live (a 10-minute stall); its rules are tested.
- Workers run with the pass's rules only, no container. The folder is under the workspace, so writes there pass.

## Trying it without touching the live Odie

The branch runs as a second Odie from the worktree, with its own home and port, while the live one keeps running on
main. Scheduler off, so this copy never reads mail or calendar; the jobs you start are its only background work.

```sh
cd <the worktree of this branch>
export ODIE_HOME=$HOME/odie-workers-home ODIE_PORT=8831 ODIE_SCHEDULER=0 ODIE_PAIRING=off ODIE_WORKERS=1 ODIE_VOICE=off
export ODIE_HOSTS=127.0.0.1:8831,localhost:8831
mkdir -p $ODIE_HOME
uv run python -c "from odie import config; from odie.store.db import Store; s=Store(config.settings.db_path); s.init_schema(); s.set_setting('model.chat', {'provider':'ollama','model':'deepseek-v4.1-flash:1017-cloud'})"
uv run uvicorn odie.app.main:create_app --factory --host 127.0.0.1 --port 8831
```

Then open http://127.0.0.1:8831 in a browser on the Mac. Things to try: "write a script that … and run it" (a task on
DeepSeek), "track … every 5 minutes, only tell me when it changes" (a reporter on lfm3), a job that can't finish (a
card on Today), Settings → Brain (the small model), Today's Jobs section, and the welcome after a few hours away.
`rm -rf ~/odie-workers-home` when done. Only the Mac's browser sees this copy; the phone keeps talking to the live Odie.
