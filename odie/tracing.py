"""LangSmith traces of every chat turn: system prompt, messages (with prefetched notes and ledger lines), tool calls.
On only when LANGSMITH_API_KEY is in the environment or ~/.odie/.env. Traces upload full prompts to LangSmith."""
from __future__ import annotations

import logging
import os

from odie.secrets import load_secret

log = logging.getLogger(__name__)


def setup() -> bool:
    key = load_secret("LANGSMITH_API_KEY")
    if not key or os.environ.get("ODIE_TRACE") == "0":
        return False
    project = load_secret("LANGSMITH_PROJECT") or "odie"
    os.environ.update(LANGSMITH_API_KEY=key, LANGSMITH_PROJECT=project, LANGSMITH_TRACING="true")
    try:
        from langsmith.integrations.google_adk import configure_google_adk
        ok = configure_google_adk(name="odie.turn", project_name=project)
    except Exception:  # noqa: BLE001
        log.warning("LangSmith tracing setup failed", exc_info=True)
        return False
    if ok:
        log.info("LangSmith tracing on (project %s)", project)
    else:
        log.warning("LangSmith tracing NOT on: configure_google_adk failed (see the warning above)")
    return ok
