"""Workers (Workers design, 18 Nov 2026; brought back from the 4 Nov spike): long jobs run in the background so the
chat stays free.

The chat is the manager. When a request takes many steps, the shell, or minutes of work, the chat agent calls
start_job, says "Started", and a Worker does the job: its own agent session with the brief as its first message, its
own folder under the workspace, the shell, its own files, web reads, and the connected apps of the personality that
started it, thinking with that personality's brain. It never asks the user anything: it follows the Smart rules, and a
step those rules would card (delete or stop, install, secrets, Odie itself, sending out) is refused and noted; its
report says "I needed to do X", and Pulse offers "Allow it and run again", a tap in the app that covers that job's next
run only. Its report is posted into the chat that started it, with a push. Every tool call and every refusal is a row
in job_actions.

Odie's own jobs (a loop's step, such as testing a pull request: odie.loops.pr_test) run in the same slots, run by code,
at most 2 at once so one of the 3 slots is always the user's, and 8 a day.

Modules: store (the tables), router (slots, start, stop, retry, recovery), worker (one run), allow (what a tap allows),
watchdog (every minute), tools (the chat's), nudge (the line on job-like messages), cards (Pulse), files."""
