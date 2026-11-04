# Workers: the spike (November 2026)

An experiment on the branch `workers-spike`, switched on with `ODIE_WORKERS=1` and off by default. It tries the Worker
half of DeepSeek Harness's "Exploring Super-agent Design" (31 October 2026) inside Odie: a long job the user asks for
in chat runs in a background Worker of its own and reports back into the chat. Three questions it should answer:

1. Can the kinds that don't need the main model (a reporter, a mail summary) run on a small local model?
2. How are Worker errors caught, and who starts a job again?
3. How does data flow from the chat to the Router to the Worker and back, as one system?

## What is built (step 1)

- `start_job`, `jobs_status`, `stop_job` in the chat; the docstrings carry the rule for when to delegate.
- `odie/workers/router.py`: plain code. Writes the job row, makes `<workspace>/jobs/<slug>-<id>/`, runs the Worker in
  its own task. At most 3 at a time.
- `odie/workers/worker.py`: one ADK session per job with the kind's instruction and tools plus `report`. No Odie
  prompt, memory or chat history. Ends on `report`; otherwise one nudge, then the job fails. A budget (30 minutes)
  and a call cap (80) end it too.
- `odie/workers/kinds.py`: the `task` kind: the shell without a tap but behind the pass's always-ask rules (a refused
  command fails with the rule's words), `write_file` and `read_file` inside the job folder, web search and fetch.
- `odie/workers/store.py` and `schema.sql`: the `jobs` and `job_actions` tables. Every call, its result size and every
  refusal is a row.
- The chat the job came from gets one message (done, stuck, nothing to do, didn't finish) with a push.

## Data flow

Chat (the model) decides the job is long and calls `start_job(title, brief)` -> Router writes the row and folder,
starts the task -> Worker runs with the brief as its first message, its calls go to `job_actions` -> `report(outcome,
text, files)` -> Router stores it and posts the message into the chat with a push -> the next chat turn sees it as
history. Nothing else crosses: the chat sees the brief going out and the report coming back.

## Live findings (4 November, DeepSeek V4.1 Flash as the chat model, throwaway home)

| Job | Calls | Refusals | Wall time |
|---|---|---|---|
| Fibonacci script, before `write_file` | 26 | 6 | 37 s |
| Mac health check (disk, memory, uptime) | 6 | 0 | 11 s |
| Primes below 100 script, after `write_file` | 6 | 1 | 10 s |

- The chat delegated on its own when the message said "in the background". Without those words it once tried the
  shell itself and raised an approval card instead. The rule in the `start_job` docstring needs more live turns to
  judge.
- The two later jobs ran in parallel (started 4 s apart, both done within 14 s).
- Before `write_file`, every file went through the shell: heredocs with backticks in a docstring tripped "runs text
  as commands", and a relative path outside the folder tripped "writes a file outside /tmp". With `write_file` the
  same kind of job needed 6 calls.
- A Worker never asked anything and never touched the user's pass: a refused command is recorded with the rule's
  words and the Worker went on.
- The chat recognised a repeat request ("Already done a few minutes ago, job-…") from its own history: the report
  posted into the chat is enough context for follow-ups.
- The throwaway home under `/tmp` confused the Worker once: the chat shell only runs under the user's home. A real
  install's workspace is under `~/.odie`, so this is an artefact of the test setup.

## Not yet built

- Step 2: the reporter kind (a schedule; a report each run until stopped) and the mail kind (may send, no shell,
  recipients fixed at start).
- Step 3: the watchdog reading the store (budget, stall, same error three times), restarts for passing errors, a
  Retry on the job card, and what a restart of Odie does with running jobs (today: they are lost silently).
- Step 4: a kind on a small local model (Gemma 4 12B, then LFM 1.7B) and what it can and cannot do.
- A Running list on Today with Stop; the job card's log in the chat.
