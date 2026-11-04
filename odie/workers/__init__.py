"""Workers: long jobs the user asks for in chat, run in the background by an agent of their own (spike, Nov 2026).

Odie stays the one the user talks to. When a request takes many steps, the shell, or minutes of work, the chat agent
calls start_job instead of doing it in the turn, says "Started", and a Worker does the job: its own agent session, its
own folder under the workspace, the tools its kind allows, no Odie prompt, no memory, no chat history. It never asks the
user anything. It ends by calling report; the report is posted into the chat the job came from, with a push. Every tool
call and every refusal is a row in job_actions, so the record is complete whether or not anyone was watching.

The design follows the Worker half of DeepSeek Harness's "Exploring Super-agent Design" (Oct 2026): isolated Workers
that report to the one session that talks to people. The Router there is a model; here the chat agent is the router
and the dispatch is plain code (odie.workers.router).

Switched on with ODIE_WORKERS=1. Off (the default) nothing here is loaded: no tools, no tables, no prompt change."""
from __future__ import annotations


def enabled() -> bool:
    """Whether workers are switched on for this server: ODIE_WORKERS=1 -> True; unset, "0" or anything else -> False."""
    import os
    return os.environ.get("ODIE_WORKERS", "0") == "1"
