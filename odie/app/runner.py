"""Owns the ADK Runner. One session per calendar day. Builds the per-request system prompt
(now, memory prefetch, ledger) through an InstructionProvider."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid

import json
from google.adk.events import Event
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from odie import addons, config
from odie.agent.agent import build_agent, chat_generate_config, memory_file
from odie.agent.callbacks import OdiePlugin
from odie.agent.context import parts_of
from odie.agent.model import WRITER_REPLY_TOKENS, model_for
from odie.making.writer import MAX_LLM_CALLS as WRITER_MAX_LLM_CALLS
from odie.models import chat_completion, context_window, history_limit_for, resolve_selection
from odie.sampling import BACKGROUND_TEMPERATURE
from odie.agent.prompt import ALL_CAPS, Who, build_static_prompt, build_turn_context, format_open_threads
from odie.agent.agent import GATED_TOOLS
from odie.agent.tools.local import threads_summary
from odie.app.events import EventBus
from odie.memory.index import build_index, render_prefetch
from odie.memory.review import run_review
from odie.memory.search import prefetch_hits
from odie.push.send import send_to_all
from odie.store.db import Store

log = logging.getLogger("odie.runner")


IMAGE_MARK = re.compile(r"\n?\[image:([0-9a-f]{6,64})\]")


def strip_trailer(text: str) -> str:
    """Remove what Odie adds after the user's words (prefetched blocks, the [context ...] note) before showing history."""
    from odie.agent.prefetch import block_starts
    cuts = [i for i in (text.find(m) for m in block_starts()) if i >= 0]
    i = text.rfind("\n\n[context: ")
    if i >= 0:
        cuts.append(i)
    return text[:min(cuts)] if cuts else text


def split_images(text: str) -> tuple[str, list[str]]:
    ids = IMAGE_MARK.findall(text)
    return IMAGE_MARK.sub("", text).strip(), ids


def merge_approvals(items: list[dict[str, Any]], rows: list[Any]) -> list[dict[str, Any]]:
    """Put each approval card where it happened, so decided ones stay visible after a reload."""
    from odie.store.db import approval_dict
    out = list(items)
    for row in rows:
        a = approval_dict(row)
        try:
            ts = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            ts = 0.0
        card = {"role": "approval", "text": "", "tools": [], "ts": ts, "approval": a}
        at = next((i for i, m in enumerate(out) if (m.get("ts") or 0) > ts), len(out))
        out.insert(at, card)
    return out


def with_session(sid: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each Odie reply that has a key also says which session it is in, so the app knows where its ticks are saved:
    today's chat can span segments (chat-2026-10-11, then chat-2026-10-11-2 after New chat)."""
    for it in items:
        if it.get("key"):
            it["sid"] = sid
    return items


def media_of(response: Any) -> dict[str, Any] | None:
    """What a tool made for the chat (odie.media), when its result carries one: the full description from its sidecar
    (the tool's result, which the model sees, carries only the id, kind, title and length)."""
    from odie import media
    m = response.get("media") if isinstance(response, dict) else None
    if not (isinstance(m, dict) and isinstance(m.get("id"), str) and media.ID_RE.match(m["id"]) and m.get("kind") in media.KINDS):
        return None
    got = media.get(m["id"])
    return got[1] if got else m


def events_to_history(events: list[Any]) -> list[dict[str, Any]]:
    """Session events -> [{role, text, tools, ts, inv?, media?, key?}], tool calls (and what they made) folded into the
    following Odie text. key: the id of the event an Odie text came from, which names that reply for good (its saved
    checklist ticks hang off it; see reply_key). inv: the turn the line came from (the event's invocation id), so an
    app can fold a turn's lines into one answer; a message Odie posted on its own is a turn of its own."""
    out: list[dict[str, Any]] = []
    hidden = GATED_TOOLS | addons.gated_tools()  # gated calls are shown by their approval card

    def line(role: str, text: str, tools: list[str], ts: float, inv: str, **more: Any) -> dict[str, Any]:
        item: dict[str, Any] = {"role": role, "text": text, "tools": tools, "ts": ts, **more}
        if inv:
            item["inv"] = inv
        return item

    for ev in events:
        if not ev.content or not ev.content.parts or getattr(ev, "partial", False):
            continue
        ts = float(getattr(ev, "timestamp", 0) or 0)
        inv = str(getattr(ev, "invocation_id", "") or "")
        texts = [p.text for p in ev.content.parts if p.text and not getattr(p, "thought", False)]  # a model's reasoning is its own, not a reply
        tools = [p.function_call.name for p in ev.content.parts if p.function_call and p.function_call.name != CONFIRM and p.function_call.name not in hidden]
        made = [m for p in ev.content.parts if p.function_response and (m := media_of(p.function_response.response))]
        if made and ev.author != "user":
            if out and out[-1]["role"] == "odie" and not out[-1]["text"]:
                out[-1].setdefault("media", []).extend(made)
            else:
                out.append(line("odie", "", [], ts, inv, media=made))
            continue
        if ev.author == "user":
            if texts and "".join(texts).startswith(CHECK_PREFIX):
                continue  # a code-made nudge, not something the user said
            if texts:
                clean, imgs = split_images(strip_trailer("".join(texts)))
                out.append(line("user", clean, [], ts, inv, images=imgs))
            continue
        if tools:
            if out and out[-1]["role"] == "odie" and not out[-1]["text"]:
                out[-1]["tools"] += tools
            else:
                out.append(line("odie", "", tools, ts, inv))
        if texts:
            if out and out[-1]["role"] == "odie" and not out[-1]["text"]:
                out[-1]["text"] = "".join(texts)
            else:
                out.append(line("odie", "".join(texts), [], ts, inv))
            key = reply_key(ev)
            if key:
                out[-1]["key"] = key
            usage = usage_of(ev)
            if usage:
                out[-1]["usage"] = usage
            posted = [m for x in ((getattr(ev, "custom_metadata", None) or {}).get("media") or []) if (m := media_of({"media": x}))]
            if posted:  # a posted message's memo (a spoken reminder)
                out[-1].setdefault("media", []).extend(posted)
    return out


CONFIRM = "adk_request_confirmation"
CHECK_PREFIX = "[odie check] "  # a nudge from code, never shown in history
CHECK_TEXT = ("Your reply says it was saved, but {tool} was never called, so nothing was saved. Call {tool} now with the "
              "details from the user's message, then confirm in one short line. Don't apologise at length.")
_CLAIMS = {
    "task_add": re.compile(
        r"\b(i(?:'|\s+ha)ve|i've)\s+(?:now\s+)?(?:set|scheduled|added|created|saved)\b[^.?!]*\b(?:remind|reminder|task|to-?do|alarm)"
        r"|\breminder\s+(?:is\s+)?(?:set|scheduled|saved|added|created)\b|\bi'?ll\s+remind\s+you\b", re.I),
    "track": re.compile(
        r"\b(i(?:'|\s+ha)ve|i've)\s+(?:now\s+)?(?:set up|started|created|added)\s+(?:a\s+)?track"
        r"|\b(?:i'?m|i am)\s+(?:now\s+)?tracking\b|\btracking\s+(?:it|this|that)\s+now\b", re.I),
}
_DONE_BY = {"task_add": {"task_add", "task_update", "task_list"}, "track": {"track", "list_trackers"}}  # listing = describing ones that exist


def _tool_error(resp: Any) -> str | None:
    """The error text of a failed tool result, or None if it worked."""
    if not isinstance(resp, dict):
        return None
    if not (resp.get("isError") or "error" in resp):
        return None
    texts = [c.get("text", "") for c in resp.get("content") or [] if isinstance(c, dict)] or [str(resp.get("error", ""))]
    for t in texts:
        try:
            d = json.loads(t)
            if isinstance(d, dict) and (d.get("message") or d.get("error")):
                return str(d.get("message") or d.get("error"))[:200]
        except ValueError:
            pass
    return " ".join(texts)[:200] or "it failed"


def same_failure_again(ev: Any, fails: dict[tuple[str, str], int], limit: int = 3) -> str | None:
    """A model stuck retrying a call that keeps failing the same way: the third time, the turn stops with this note."""
    for p in parts_of(ev):
        fr = p.function_response
        if not fr:
            continue
        err = _tool_error(fr.response)
        if not err:
            continue
        key = (fr.name or "?", err)
        fails[key] = fails.get(key, 0) + 1
        if fails[key] >= limit:
            label = (fr.name or "a tool").replace("_", " ")
            return (f"I stopped: {label} failed the same way {limit} times (\u201c{err}\u201d), so retrying wasn't going to help. "
                    "Tell me how you'd like to go on.")
    return None


def _has_pending_call(ev: Any) -> bool:
    """An event that asks for a tool call: its result hasn't come back yet, so this isn't a safe point to stop."""
    return any(p.function_call for p in parts_of(ev))


def claimed_but_not_done(text: str, called: set[str]) -> str | None:
    """The tool a reply says it used but didn't: 'I've set a reminder' with no task_add in the turn."""
    for tool, rx in _CLAIMS.items():
        if rx.search(text or "") and not (called & _DONE_BY[tool]):
            return tool
    return None
_ANNOUNCE = re.compile(r"^(here(?:'s| is| are| it is)|below is|i've drawn|drawn below)\b[^:]*:?\s*$", re.I)
_CONTENT = re.compile(r"^\s*([-*•]|\d+[.)]|\|)", re.M)
PROMISE_TEXT = ("Your reply announces the answer but doesn't include it. Send it now: drawn with blocks "
                "(an ```odie-blocks fence: a timeline, a table, tiles or a chart), with a line or two of text.")


def promised_but_empty(reply: str, called: set[str]) -> bool:
    """A reply after tool work whose last sentence only announces its content ("Here's the full plan — …") and that
    carries none: no block, no list, no table. Some models end the turn there, with the plan left in their reasoning."""
    r = (reply or "").strip()
    if not r or not called or "```" in r or _CONTENT.search(r) or len(r) > 600:
        return False
    last = re.split(r"(?<=[.!?])\s*(?=[A-Z])", r)[-1].strip()
    return bool(_ANNOUNCE.match(last))


# A background turn's system prompt ends with this. The time goes in its message instead: the system prompt stays the
# same from one check to the next, so the provider can reuse it (with the tools before it) from its cache.
BACKGROUND_INSTRUCTION = ("You are Odie, the user's assistant, running a background check. Be brief and factual; use tools "
                          "for current facts; never invent them.")


# A turn may call the model this many times (tools in between). ADK's default is 500, so a model looping on a tool
# never stopped; a heavy skill turn (a 2-day itinerary with ten searches) uses about 15.
MAX_LLM_CALLS = 40


def chat_run_config() -> RunConfig:
    return RunConfig(streaming_mode=StreamingMode.SSE, max_llm_calls=MAX_LLM_CALLS)


def chat_error(e: Exception) -> str:
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError
    if isinstance(e, LlmCallsLimitExceededError):
        return f"I stopped after {MAX_LLM_CALLS} steps without finishing; ask again more narrowly, or I can try a different way."
    return f"{type(e).__name__}: {str(e)[:200]}"


def _safely(fn, *args):
    """An add-on watcher's call; a failure is logged and counts as nothing."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        log.warning("an add-on turn check failed", exc_info=True)
        return None


def approval_from_confirmation(fc: Any, invocation_id: str, session_id: str, store: Store) -> dict[str, Any]:
    """Code, not the model, writes what the card says: the summary comes from the tool arguments (an add-on writes the
    card for its own tools, from its audit log), provenance from the mail the model has seen recently in this session."""
    from odie.signin import guard as signin_guard
    args = dict(fc.args or {})
    orig = args.get("originalFunctionCall") or {}
    tool = orig.get("name", "?")
    targs = dict(orig.get("args") or {})
    detail: dict[str, Any] = dict(targs)
    risk = "normal"
    if tool == "install_skill":
        from odie.skills import builder
        name = str(targs.get("name", ""))
        code = (builder.staging_dir() / name / "tools.py").exists()
        summary = f"Install skill {name}" + (" (runs code on this computer)" if code else " (instructions only)")
        detail["body"] = builder.staged_text(name) or "(no draft found: decline)"
        same = str(targs.get("version", "")) == builder.staged_version(name)
        risk = "normal" if detail["body"].startswith("──") and same else "unknown"
    elif tool == "run_shell":
        cwd = targs.get("cwd") or "~"
        detail["cwd"] = cwd
        summary = f"Run in {cwd}: {targs.get('command', '')}"
    elif tool in signin_guard.GUARDED:
        summary, extra = signin_guard.card(tool, targs, session_id, store)
        detail.update({k: v for k, v in extra.items() if v})
    elif card := next((c for c in addons.call("card", tool, targs, session_id, store) if c), None):
        summary, risk = card.summary, card.risk
        detail.update(card.detail)
    else:
        from odie.plugins.mcp import TOOL_APP
        app = TOOL_APP.get(tool)
        label = tool.replace("_", " ").capitalize()
        args_text = "; ".join(f"{k}: {str(v)[:60]}" for k, v in targs.items())
        if app:
            detail["app"] = app
            summary = (f"{label} in {app}" + (f": {args_text}" if args_text else ""))[:200]
        else:
            summary = f"{label}: {args_text}"[:160] if args_text else label
    from odie.agent import turn
    if private := turn.private_sites():  # a tap resumes this turn: it stays private (resume_approval)
        detail["private"] = sorted(private)
    mails = store.recent_mail_seen(session_id)
    if risk == "normal" and mails:
        risk = "from_email" if any(m.get("turn") == "current" for m in mails) else "mail_earlier"
    return {"tool": tool, "args": targs, "request_id": fc.id, "invocation_id": invocation_id, "session_id": session_id,
            "summary": summary, "detail": detail, "provenance": mails, "risk": risk}


def push_body(a: dict) -> str:
    """The lock-screen line for an approval: what, never the private details."""
    if a["tool"] == "run_shell":
        return "Run a command"
    if (a.get("detail") or {}).get("app"):
        return f"{a['tool'].replace('_', ' ').capitalize()} in {a['detail']['app']}"
    return a["summary"][:120]


NEW_CHAT = "(New chat.)"  # first event of a segment the user started by hand; the web app draws it as a divider


def model_key(sel) -> str:
    """Which model a Selection runs, as text to compare: the provider, its address and the model's name. A different
    one means the agent's model must be rebuilt (or the context size read again)."""
    return f"{sel.provider.id}|{sel.provider.base_url}|{sel.model}"


def session_id_for(now: datetime) -> str:
    return "chat-" + now.strftime("%Y-%m-%d")


def usage_of(ev: Any) -> dict[str, int] | None:
    """The token counts of the model call an event came from, as the chat shows them under the reply: input, how much of
    it the provider read from its prompt cache, output. None when the event carries no counts (a streamed piece, a tool
    result, an older event).
      prompt 9,800 of which 8,900 cached, 250 out  -> {"input": 9800, "cached": 8900, "output": 250}
      a tool's result (no model call)              -> None"""
    u = getattr(ev, "usage_metadata", None)
    if not u or not u.prompt_token_count:
        return None
    return {"input": u.prompt_token_count, "cached": u.cached_content_token_count or 0, "output": u.candidates_token_count or 0}


def event_to_sse(ev: Any) -> list[dict[str, Any]]:
    if getattr(ev, "author", None) == "user" or not getattr(ev, "content", None) or not ev.content.parts:
        return []
    out: list[dict[str, Any]] = []
    partial = bool(getattr(ev, "partial", False))
    hidden = GATED_TOOLS | addons.gated_tools()
    for p in ev.content.parts:
        if getattr(p, "thought", False):  # the model's reasoning (DeepSeek's, Gemma's, Claude's summary): never shown as the reply
            continue
        if p.function_call:
            if not partial and p.function_call.name not in hidden:  # gated calls are shown by their approval card
                out.append({"type": "tool_start", "tool": p.function_call.name, "args": dict(p.function_call.args or {})})
        elif p.function_response:
            if not partial and p.function_response.name not in hidden:
                out.append({"type": "tool_done", "tool": p.function_response.name})
                m = media_of(p.function_response.response)
                if m:
                    out.append({"type": "media", "media": m})
        elif p.text:
            item = {"type": "token" if ev.partial else "text", "text": p.text}
            key = reply_key(ev)
            if key:
                item["key"] = key
            usage = None if partial else usage_of(ev)
            if usage:
                item["usage"] = usage  # the finished reply's counts, for the line under it
            out.append(item)
    return out


def reply_key(ev: Any) -> str | None:
    """The name a reply keeps for good: the id of the ADK event its text came from. It is the same while the reply
    streams in and after any reload: ADK gives a response's streamed pieces the id of the finished event, and the
    session store keeps that id. The app saves a reply's checklist ticks under (session id, this key).
      an event with id "3f2b9c1e-5d…" → "3f2b9c1e-5d…";  a test double without an id → None (nothing is saved)"""
    key = getattr(ev, "id", None)
    if isinstance(key, str) and key:
        return key
    return None


def tool_error_as_result(tool, args, tool_context, error: Exception) -> dict:
    """Decides what a focused turn's model sees when one of its tools raises: the error as the tool's result, so the model
    can fix its input and call again, instead of the whole turn aborting. Only the first line of the error, cut to 300
    characters. Example: a tool raising ValueError("page has no title\nat line 3") -> {"error": "ValueError: page has no
    title"}. The full exception goes to the log."""
    log.warning("focused turn: tool %s raised", tool.name, exc_info=error)
    first_line = str(error).splitlines()[0] if str(error) else ""
    return {"error": f"{type(error).__name__}: {first_line}"[:300]}


class OdieRunner:
    def __init__(self, store: Store):
        s = config.settings
        self.store = store
        self.tz = ZoneInfo(s.timezone)
        self._current_prompt = ""
        self._prompt_session = ""
        self._model_key: tuple | None = None
        self.gated = True  # approval-gated tools are loaded (send, trash, invites, shell)
        self.memory = memory_file()
        self.memory.ensure()
        self.bus = EventBus()
        self._locks: dict[str, asyncio.Lock] = {}
        self._compact_limits: dict[str, int] = {}  # session -> its compaction limit (_compact_at)
        self._recent: dict[str, list[str]] = {}  # previous two user questions per session, for prefetch  # one per session: a reminder never appends mid-turn
        self.history_limit = history_limit_for(None)  # tokens; until the model's real context size is known
        self._limit_key: tuple | None = None
        self.plugins: dict = {"skills": [], "servers": []}
        self._stop: set[str] = set()  # sessions the user asked to stop
        from odie.skills import builder
        builder.hooks.update(store=store, reload=self.load_plugins, reserved=lambda: self._all_tool_names())
        from odie import trackers
        trackers.hooks.update(store=store, tz=self.tz)
        from odie import about
        about.hooks.update(runner=self)
        from odie.making import jobs as making_jobs
        making_jobs.hooks.update(runner=self, store=store)
        self._plugin_toolsets: list = []  # MCP connections owned by the current plugin set
        self._plugins_lock = asyncio.Lock()  # one reload at a time, each reading the latest config
        self.close_grace = 120.0  # seconds old connections stay open after a reload, for a turn still using them
        self.retry_every = 45.0   # a failed server (the vault still starting at boot) is tried again this often
        self._retries_left = 8
        self._background: set[asyncio.Task] = set()
        self.review_every = config.settings.review_every_turns
        self._turns: list[tuple[str, str]] = []   # (user, assistant) pairs since the last review
        self._review_task: asyncio.Task | None = None
        self.agent = build_agent(store, instruction=lambda ctx: self._current_prompt, memory=self.memory,
                                 on_memory_change=self._memory_changed)
        self.plugin = OdiePlugin(store)
        from odie.agent.usage import CACHE
        app = App(name=s.app_name, root_agent=self.agent, plugins=[self.plugin],
                  resumability_config=ResumabilityConfig(is_resumable=True), context_cache_config=CACHE)
        s.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_service = SqliteSessionService(db_path=str(s.sessions_db_path))
        self.runner = Runner(app=app, session_service=self.session_service)

    # ── sessions: one thread per day, rolled into numbered segments when it grows too large ──
    def current_session_id(self, date: str) -> str:
        row = self.store.one("select value_json from settings where key=?", (f"segment:{date}",))
        n = int(row["value_json"]) if row else 1
        return f"chat-{date}" if n == 1 else f"chat-{date}-{n}"

    def _set_segment(self, date: str, n: int) -> None:
        self.store.execute("insert into settings(key,value_json) values(?,?) on conflict(key) do update set value_json=excluded.value_json",
                           (f"segment:{date}", str(n)))

    async def _recent_questions(self, session_id: str) -> list[str]:
        """The previous two user questions in this session, most recent first (loaded once from the session)."""
        if session_id not in self._recent:
            s = config.settings
            sess = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=session_id)
            texts = [h["text"] for h in events_to_history(sess.events if sess else []) if h["role"] == "user" and h["text"]]
            self._recent[session_id] = texts[-2:][::-1]
        return list(self._recent[session_id])

    async def _words_of(self, session_id: str, invocation_id: str) -> str:
        """What the user said to start this invocation ("" if it's gone)."""
        s = config.settings
        sess = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=session_id)
        for ev in reversed(sess.events if sess else []):
            if ev.author == "user" and ev.invocation_id == invocation_id and ev.content and ev.content.parts:
                if text := "".join(p.text or "" for p in ev.content.parts):
                    return text
        return ""

    async def _compact_at(self, session_id: str) -> int:
        """This chat's limit in characters (odie.agent.compaction), from the chosen model's context size, read at the
        session's first turn and then kept for the session: a limit that moved mid-chat would move the cut and rewrite
        history the model has already read.
          the first turn of chat-2026-10-15 with DeepSeek (1M)  -> 1,136,000, kept for chat-2026-10-15
          a later turn there, after switching to Gemma (70k)    -> still 1,136,000 (the next session uses Gemma's)
          a provider that can't say its size                    -> 136,000"""
        if session_id not in self._compact_limits:
            from odie.agent import compaction
            await self.refresh_history_limit()
            self._compact_limits[session_id] = compaction.compact_at(self.history_limit)
        return self._compact_limits[session_id]

    async def _visual_nudge(self, session_id: str, text: str) -> str:
        """The line that reminds the model to draw (odie.agent.visual_nudge), with a line break before it, when this
        message looks like it reads better drawn; "" otherwise. The previous reply is read only for a short message
        ("yes"), the one case that needs it.
          "Packing list for Ooty"                     -> a line break, then "[If this reads better drawn, …]"
          "yes", after a reply that drew a checklist  -> the same
          "Remind me at 9 to call the bank"           -> nothing ("")"""
        from odie.agent import visual_nudge
        previous = ""
        if visual_nudge.is_short(text):
            previous = await self._last_reply(session_id)
        if not visual_nudge.looks_visual(text, previous):
            return ""
        self.store.audit("agent", "visual_nudge", result_summary=text[:200], session_id=session_id)
        return "\n" + visual_nudge.NUDGE

    async def _last_reply(self, session_id: str) -> str:
        """Odie's whole reply to the user's last message in this session ("" when there's none yet)."""
        s = config.settings
        sess = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=session_id)
        replies: list[str] = []
        for item in reversed(events_to_history(sess.events if sess else [])):
            if item["role"] == "user":
                break
            replies.append(item["text"])
        return "\n".join(reversed(replies))

    def _remember_question(self, session_id: str, text: str) -> None:
        self._recent[session_id] = [text, *self._recent.get(session_id, [])][:2]

    def lock_for(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def _ensure_session(self, session_id: str) -> str:
        s = config.settings
        existing = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=session_id)
        if existing is None:
            await self.session_service.create_session(app_name=s.app_name, user_id=s.user_id, session_id=session_id)
        return session_id

    def memory_index(self) -> str:
        try:
            return build_index(self.memory.load(), max_chars=5000)
        except OSError:
            return ""

    def prefetch(self, text: str) -> str:
        try:
            hits = prefetch_hits(self.memory.load().entries(), text, limit=4)
        except OSError:
            return ""
        rendered, _ = render_prefetch(hits, max_entries=4, max_chars=2500)
        return rendered

    def _note_turn(self, user: str, assistant: str) -> None:
        """Every N user turns, review the conversation for things worth remembering (background)."""
        self._turns.append((user, assistant))
        if len(self._turns) < self.review_every:
            return
        turns, self._turns = self._turns, []
        if self._review_task is None or self._review_task.done():
            self._review_task = asyncio.create_task(run_review(self.memory, turns, self.memory_index(), on_change=self._memory_changed, store=self.store))

    def _memory_changed(self) -> None:
        """The memory file changed (update_memory, the review): when it's in the vault, the notes index re-reads it.
        The system prompt keeps the memory titles it started the chat with: rebuilding it mid-chat would change the
        very start of every later request, so the model would read the whole conversation again (and Claude would drop
        its kept thoughts). The change still reaches the model: each message's [memories] block searches the memory
        as it is now, search_memories and fetch_memory read it live, and the next chat (tomorrow, or a new chat) lists
        the new titles.
          "Remember I prefer aisle seats" at 10:00 -> saved; this chat's system prompt is unchanged
          "Which seat do I like?" at 10:05         -> the [memories] block finds the new entry"""
        worker = getattr(self, "vault_worker", None)
        if worker is not None:
            worker.touch(self.memory.path)

    async def reload_vault(self) -> None:
        """The vault setting changed: swap the notes tools, then reload the apps (an MCP server with the same tool
        names is refused while the built-in index is on, and comes back when it's off)."""
        from odie.agent.agent import vault_tools
        tools = [t for t in self.agent.tools if not getattr(t, "_odie_vault", False)]
        self.agent.tools = vault_tools(self.store) + tools
        self.invalidate_prompt()
        await self.load_plugins()

    async def reload_signin(self) -> None:
        """Signed-in browsing was switched on or off: swap the sign-in tool; its rules follow on the next message."""
        from odie.agent.agent import signin_tools
        tools = [t for t in self.agent.tools if not getattr(t, "_odie_signin", False)]
        self.agent.tools = signin_tools(self.store) + tools
        self.invalidate_prompt()

    def invalidate_prompt(self) -> None:
        """Rebuild the static prompt on the next message (SOUL.md or memory index changed)."""
        self._prompt_session = ""

    def apply_model_selection(self) -> None:
        """Settings changed the chat model: the next message builds the agent's model from the new selection."""
        self._model_key = None
        self.invalidate_prompt()

    def current_model(self) -> dict[str, Any]:
        sel = resolve_selection(self.store, "chat")
        return {"provider": sel.provider.id, "model": sel.model, "leaves_mini": sel.leaves_mini}

    @staticmethod
    def load_soul() -> str | None:
        from odie.app import routes  # single source of truth for the path
        try:
            txt = routes.SOUL_PATH.read_text().strip()
        except OSError:
            return None
        return txt or None

    def _prepare_prompt(self, session_id: str, text: str) -> str:
        """Static system prompt once per session (cache-friendly); returns the per-turn context trailer."""
        now = datetime.now(self.tz)
        if session_id != self._prompt_session:
            from odie import persona
            who = self.who()
            self._caps = who.caps
            self._current_prompt = persona.apply_name(build_static_prompt(now, self.load_soul(), self.memory_index(), gated=self.gated,
                                                                          who=who), persona.get(self.store)["name"])
            self._prompt_session = session_id
        rows = self.store.open_tasks(now.isoformat(timespec="minutes"))[:10]
        brief = self.store.one("select text from briefs where date=? order by id desc limit 1", (now.strftime("%Y-%m-%d"),))
        return build_turn_context(now, self.prefetch(text), threads_summary(self.store), format_open_threads(rows),
                                  brief["text"] if brief else "", caps=getattr(self, "_caps", ALL_CAPS))

    def who(self) -> Who:
        """Who the prompt is for: the profile's name, this computer, the local currency, what this install can do, and
        the assistant's chosen name."""
        from odie import capabilities, persona, profile, region
        return Who(user=profile.get(self.store)["user_name"], machine=profile.machine_kind(),
                   currency=region.currency_symbol(config.settings.currency), caps=capabilities.detect(self.plugins.get("servers", []), self.store),
                   assistant=persona.get(self.store)["name"])

    async def chat(self, text: str, thinking: bool = False, session_id: str | None = None,
                   images: list[str] | None = None) -> AsyncIterator[dict[str, Any]]:
        """One user turn. session_id defaults to today's chat session; pass one to start elsewhere (eval, new thread).
        images: upload ids; each becomes an inline image part the vision model sees, and an [image:id] marker in the text."""
        s = config.settings
        today = datetime.now(self.tz).strftime("%Y-%m-%d")
        session_id = session_id or self.current_session_id(today)
        lock = self.lock_for(session_id)
        await lock.acquire()
        turn_token = private_token = compact_token = None
        was_private = False
        try:
            session_id = await self._ensure_session(session_id)
            trailer = self._prepare_prompt(session_id, text) + await self._visual_nudge(session_id, text)
            parts: list[types.Part] = []
            markers = ""
            for iid in images or []:
                from odie.app.images import load_image
                got = load_image(iid)
                if got:
                    parts.append(types.Part(inline_data=types.Blob(mime_type=got[1], data=got[0])))
                    markers += f"\n[image:{iid}]"
            blocks = ""
            if config.settings.prefetch:
                from odie.agent import prefetch
                previous = await self._recent_questions(session_id)
                blocks = await prefetch.gather(text, previous)
                if prefetch.should_search(text):
                    kinds = [o.split(":")[0].strip("[") for o, _ in prefetch.block_marks() if o in blocks]
                    self.store.audit("agent", "prefetch", result_summary=f"chars={len(blocks)} blocks={','.join(kinds) or 'none'}",
                                     session_id=session_id)
            self._remember_question(session_id, text)
            from odie.agent import turn as turn_words
            turn_token = turn_words.USER_TEXT.set(text)  # the user's own words, for tools that act only when asked
            from odie.signin import guard as signin_guard  # the signed-in sites this chat has read (signed-in browsing)
            private_token = turn_words.PRIVATE.set(signin_guard.private_of(self.store, session_id))
            compact_token = turn_words.COMPACT_AT.set(await self._compact_at(session_id))
            sent_text = f"{text}{markers}" + (f"\n\n{blocks}" if blocks else "") + f"\n\n{trailer}"
            parts.insert(0, types.Part(text=sent_text))
            selection = resolve_selection(self.store, "chat")
            key = (thinking, model_key(selection))  # the chosen model, or the fallback when nothing is chosen
            if key != self._model_key:
                self._model_key = key
                self.agent.model = model_for(selection, thinking)
            self.agent.generate_content_config = chat_generate_config(self.store)  # Creativity, as set right now
            self.store.audit("user", "message", result_summary=text, session_id=session_id)
            final: list[str] = []
            called: set[str] = set()
            unsaved = False
            unsaved_note = ""
            halt: str | None = None
            stopped = False
            turn_started = datetime.now(UTC).isoformat()
            message = types.Content(role="user", parts=parts)
            self._stop.discard(session_id)
            fails: dict[tuple[str, str], int] = {}
            checks = [c for c in addons.call("turn_check") if c is not None]  # each add-on's watcher for this turn
            nudge = None
            said_private = False
            for attempt in range(2):
                text_before = len(final)
                async with aclosing(self.runner.run_async(user_id=s.user_id, session_id=session_id, new_message=message,
                                                          run_config=chat_run_config())) as events:
                    async for ev in events:
                        for item in event_to_sse(ev):
                            if item["type"] in ("token", "text") and not said_private and turn_words.private_sites():
                                said_private = True
                                yield {"type": "private"}  # the app holds web images in this reply until a tap
                            if item["type"] == "text":
                                final.append(item["text"])
                            if item["type"] in ("token", "text"):
                                item["session_id"] = session_id  # with its key, where the reply's checklist ticks are saved
                            if item["type"] == "tool_start":
                                called.add(item["tool"])
                                if item["tool"] == CONFIRM:
                                    continue  # surfaced as an approval card below, not as a tool chip
                            yield item
                        for card in self._approvals_in(ev, session_id):
                            called.add(card.get("tool", ""))
                            await self.bus.publish(card)  # live too: the stream is cut if the app went to the background
                            yield card
                        for c in checks:
                            _safely(c.see, ev)
                        called.update(p.function_call.name for p in parts_of(ev)
                                      if p.function_call and p.function_call.name)  # gated calls too (no step chip for those)
                        halt = halt or same_failure_again(ev, fails)
                        # Stop (the user's tap) or a loop: end at a safe point, never between a tool call and its result.
                        if (halt or session_id in self._stop) and not _has_pending_call(ev):
                            break
                if halt or session_id in self._stop:
                    stopped = session_id in self._stop
                    break
                missing = claimed_but_not_done("".join(final[text_before:]), called)
                nudge = None  # an add-on's nudge (and its note) only for the call it found missing in this attempt
                if not missing:
                    nudge = next((n for n in (_safely(c.missing, text, called) for c in checks) if n), None)
                    missing = nudge.tool if nudge else None
                if not missing and attempt == 0 and promised_but_empty("".join(final[text_before:]), called):
                    # "Here's the full plan" and nothing after it: ask once, out of the user's sight, for the plan itself.
                    self.store.audit("agent", "announced_not_sent", session_id=session_id)
                    message = types.Content(role="user", parts=[types.Part(text=CHECK_PREFIX + PROMISE_TEXT)])
                    continue
                if not missing:
                    break
                if attempt == 0:
                    # The reply says something was saved but the tool never ran, or an add-on's check found a call
                    # missing (a draft left unsent): tell it once, out of the user's sight, to actually make the call.
                    self.store.audit("agent", "claimed_not_done", tool=missing, session_id=session_id)
                    said = nudge.text if nudge else CHECK_TEXT.format(tool=missing)
                    message = types.Content(role="user", parts=[types.Part(text=CHECK_PREFIX + said)])
                else:
                    unsaved = True
                    unsaved_note = (nudge.note if nudge
                                    else "That wasn't saved: I didn't manage to make the call. Ask me again and I'll set it.")
        except Exception as e:  # noqa: BLE001
            log.exception("chat failed")
            yield {"type": "error", "message": chat_error(e)}
            return
        finally:
            if turn_token is not None:
                from odie.agent import turn as turn_words
                was_private = bool(turn_words.private_sites())
                try:
                    turn_words.USER_TEXT.reset(turn_token)
                    turn_words.PRIVATE.reset(private_token)
                    if compact_token is not None:
                        turn_words.COMPACT_AT.reset(compact_token)
                except ValueError:  # iterated from another context: it ends with that context
                    pass
            lock.release()
        self._stop.discard(session_id)
        if stopped:
            await self.post_message("Stopped.", session_id=session_id)
        elif halt:
            await self.post_message(halt, session_id=session_id)
        await addons.acall("after_turn", self, turn_started, session_id)
        if unsaved:  # its own stored message, so it's in history too (the false claim stays visible above it)
            await self.post_message(unsaved_note, session_id=session_id)
        if not was_private:  # a turn that read a signed-in page never feeds the memory review
            self._note_turn(text, "".join(final))
        yield {"type": "done", "text": "".join(final)}

    def request_stop(self, session_id: str) -> None:
        """The user tapped Stop: the turn in this session ends at its next safe point."""
        self._stop.add(session_id)

    async def session_history(self, sid: str, limit: int | None = None, before: int | None = None) -> dict[str, Any]:
        """One thread's messages, oldest first, paged like history()."""
        s = config.settings
        sess = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=sid)
        items = merge_approvals(self._marked(sid, events_to_history(sess.events if sess else [])), self.store.approvals_in_sessions([sid]))
        items = with_session(sid, items)
        total = len(items)
        end = min(before, total) if before is not None else total
        start = max(0, end - limit) if limit else 0
        return {"items": items[start:end], "total": total, "start": start}

    async def history(self, date: str, limit: int | None = None, before: int | None = None) -> dict[str, Any]:
        """All segments of the day, oldest first, paged: the last `limit` items ending at index `before`."""
        s = config.settings
        items: list[dict[str, Any]] = []
        sids: list[str] = []
        n = 1
        while True:
            sid = f"chat-{date}" if n == 1 else f"chat-{date}-{n}"
            sess = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=sid)
            if sess is None:
                break
            items += with_session(sid, self._marked(sid, events_to_history(sess.events)))
            sids.append(sid)
            n += 1
        items = merge_approvals(items, self.store.approvals_in_sessions(sids))
        total = len(items)
        end = min(before, total) if before is not None else total
        start = max(0, end - limit) if limit else 0
        return {"items": items[start:end], "total": total, "start": start}

    def _marked(self, sid: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """A private segment's replies (it read a signed-in page): the app holds their web images until a tap."""
        from odie.signin import guard as signin_guard
        if signin_guard.private_of(self.store, sid):
            for it in items:
                if it.get("role") == "odie":
                    it["private"] = True
        return items

    def _approvals_in(self, ev: Any, session_id: str) -> list[dict[str, Any]]:
        """Turn ADK confirmation requests in an event into approval rows + SSE cards (+ push)."""
        if getattr(ev, "partial", False) or not getattr(ev, "content", None) or not ev.content.parts:
            return []
        cards = []
        for p in ev.content.parts:
            fc = p.function_call
            if not fc or fc.name != CONFIRM:
                continue
            inv = getattr(ev, "invocation_id", "") or ""
            a = approval_from_confirmation(fc, inv, session_id, self.store)
            aid = self.store.create_approval(session_id, inv, a["request_id"], a["tool"], a["args"], a["summary"], a["detail"], a["provenance"], a["risk"])
            self.store.audit("agent", "approval_requested", tool=a["tool"], args=a["args"], result_summary=a["summary"], session_id=session_id, invocation_id=inv, approval_id=aid)
            card = {"type": "approval", "id": aid, "tool": a["tool"], "summary": a["summary"], "detail": a["detail"],
                    "provenance": a["provenance"], "risk": a["risk"], "status": "pending"}
            cards.append(card)
            try:
                body = push_body(a)  # nothing sensitive on the lock screen
                from odie import persona
                send_to_all(self.store, f"{persona.get(self.store)['name']} needs your tap", body, url="/#chat", tag=f"approval-{aid}")
            except Exception:  # noqa: BLE001
                log.warning("approval push failed", exc_info=True)
        return cards

    async def resume_approval(self, approval_id: int, approve: bool) -> dict[str, Any]:
        """Replay the stored confirmation into the paused invocation. Exactly once; survives restarts."""
        s = config.settings
        row = self.store.get_approval(approval_id)
        if row is None:
            return {"error": "no such approval"}
        if not self.store.decide_approval(approval_id, approve):
            return {"error": f"already {self.store.get_approval(approval_id)['status']}"}
        self.store.audit("user", "approval_" + ("approved" if approve else "rejected"), tool=row["tool"], session_id=row["session_id"],
                         invocation_id=row["invocation_id"], approval_id=approval_id)
        await self.bus.publish({"type": "approval", "id": approval_id, "status": "approved" if approve else "rejected", "summary": row["summary"], "tool": row["tool"]})
        msg = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=row["request_id"], name=CONFIRM, response={"confirmed": bool(approve)}))])
        final: list[str] = []
        from odie.agent import turn
        async with self.lock_for(row["session_id"]):
            words = turn.USER_TEXT.set(await self._words_of(row["session_id"], row["invocation_id"]))  # the paused turn, resumed
            from odie.signin import guard as signin_guard
            private = turn.PRIVATE.set(set(json.loads(row["detail_json"] or "{}").get("private") or ())
                                       | signin_guard.private_of(self.store, row["session_id"]))
            compact = turn.COMPACT_AT.set(await self._compact_at(row["session_id"]))  # the same cut as the paused turn's
            try:
                async for ev in self.runner.run_async(user_id=s.user_id, session_id=row["session_id"], invocation_id=row["invocation_id"],
                                                      new_message=msg, run_config=chat_run_config()):
                    for item in event_to_sse(ev):
                        if item["type"] == "text":
                            final.append(item["text"])
                    for card in self._approvals_in(ev, row["session_id"]):
                        await self.bus.publish(card)
            except Exception as e:  # noqa: BLE001
                log.exception("resume failed")
                text = f"I couldn't finish that: {type(e).__name__}: {str(e)[:160]}"
                self.store.set_approval_result(approval_id, text)
                await self.bus.publish({"type": "approval_done", "id": approval_id, "status": "approved" if approve else "rejected", "error": text})
                return {"error": text}
            finally:
                turn.USER_TEXT.reset(words)
                turn.PRIVATE.reset(private)
                turn.COMPACT_AT.reset(compact)
        text = "".join(final) or ("Done." if approve else "Okay, I left it.")
        self.store.set_approval_result(approval_id, text)
        from odie.signin import guard as signin_guard
        await self.bus.publish({"type": "message", "kind": "reply", "text": text, "ts": time.time(), "session_id": row["session_id"],
                                **({"private": True} if signin_guard.private_of(self.store, row["session_id"]) else {})})
        await self.bus.publish({"type": "approval_done", "id": approval_id, "status": "approved" if approve else "rejected", "text": text})
        return {"text": text}

    async def reconcile_approvals(self) -> int:
        """Decided approvals whose replay never finished (restart or crash between the tap and the tool): say so, once."""
        n = 0
        for row in self.store.unfinished_approvals():
            if self.store.tool_ran_after(row["session_id"], row["tool"], row["decided_at"] or row["created_at"]):
                self.store.set_approval_result(row["id"], "Completed.")
                continue
            if row["status"] == "approved":
                text = f"Not done: I never got to this after your tap: {row['summary']}. Ask again if you still want it."
                self.store.set_approval_result(row["id"], text)
                await self.post_message(text, session_id=row["session_id"])
                n += 1
            else:
                self.store.set_approval_result(row["id"], "Declined.")
        return n

    async def background_turn(self, prompt: str, timeout: float = 300, tools: list | None = None,
                              instruction: str | None = None, guard=None, bare: bool = False) -> str:
        """One agent turn nobody watches (a tracker check, a watch check): the model, Odie's current tools (plus
        `tools`), a fresh in-memory session, and a guard that refuses anything needing the user's tap. Returns the reply.
        bare: no tools at all (a signed-in tracker's check reads text only)."""
        from google.adk.agents import LlmAgent
        from google.adk.sessions import InMemorySessionService

        from odie.trackers import guard as trackers_guard
        from odie.agent.callbacks import background_after_tool
        s = config.settings
        sel = resolve_selection(self.store, "chat")
        now = datetime.now(self.tz).strftime("%A %d %B %Y, %H:%M")
        chat_only = [t for t in self.agent.tools if not getattr(t, "_odie_signin", False)]  # signing in is the user's, in chat
        agent = LlmAgent(name="odie_tracker", model=model_for(sel, False), tools=[] if bare else [*chat_only, *(tools or [])],
                         before_tool_callback=guard or trackers_guard, after_tool_callback=background_after_tool(self.plugin),
                         instruction=(f"{instruction}\n\n" if instruction else "") + BACKGROUND_INSTRUCTION,
                         generate_content_config=types.GenerateContentConfig(temperature=BACKGROUND_TEMPERATURE))
        sessions = InMemorySessionService()
        sess = await sessions.create_session(app_name="odie_tracker", user_id=s.user_id)
        from odie.agent.usage import CACHE
        runner = Runner(app=App(name="odie_tracker", root_agent=agent, context_cache_config=CACHE), session_service=sessions)
        out: list[str] = []

        async def go():
            async for ev in runner.run_async(user_id=s.user_id, session_id=sess.id,
                                             new_message=types.Content(role="user", parts=[types.Part(text=f"It is {now} ({s.timezone}).\n\n{prompt}")])):
                if ev.content and ev.content.parts and not getattr(ev, "partial", False):
                    out.extend(p.text for p in ev.content.parts if p.text and not getattr(p, "thought", False))
        try:
            await asyncio.wait_for(go(), timeout)
        finally:
            import odie.browser as ob
            if ob._shared is not None:  # browser_open's tab is the session id: close its cookie-free context
                try:
                    await ob._shared.close_tab(sess.id)
                except Exception:  # noqa: BLE001
                    log.warning("couldn't close a background check's tab", exc_info=True)
        return "\n".join(out)

    async def focused_turn(self, prompt: str, instruction: str, tools: list, timeout: float = 600,
                           follow_up: Callable[[], str | None] | None = None,
                           max_llm_calls: int = WRITER_MAX_LLM_CALLS) -> str:
        """One agent turn that sees only what it is handed: the chat's model, `instruction` as its whole system prompt
        (no Odie prompt, no memory, no chat history), exactly the `tools` given (none of Odie's own), and a fresh
        in-memory session. Returns the reply text, thoughts left out; a turn over `timeout` seconds (follow-up
        included) raises asyncio.TimeoutError. Example: the video writer gets its writing guide and its one tool,
        nothing else. The prompt starts with the date and time, as a background check's does.
        follow_up: asked once, after the turn; a text it returns is sent as one more message in the same session (the
        video writer's nudge when it stopped without submitting), None sends nothing.
        max_llm_calls: the model calls each message may lead to (the writer's 10 by default, research 60); one more
        raises ADK's LlmCallsLimitExceededError, as a model looping on a tool would."""
        from google.adk.agents import LlmAgent
        from google.adk.sessions import InMemorySessionService

        from odie.agent.usage import CACHE
        s = config.settings
        model = model_for(resolve_selection(self.store, "chat"), False, room=WRITER_REPLY_TOKENS)
        now = datetime.now(self.tz).strftime("%A %d %B %Y, %H:%M")

        def as_written(_context) -> str:
            # Handed as a function, so ADK passes the text on untouched: a plain string would have every {name} in it
            # read as a session-state value, and the video writer's LaTeX ("\\frac{a}{b}") would fail the turn.
            return instruction

        agent = LlmAgent(name="odie_writer", model=model, tools=tools, instruction=as_written,
                         on_tool_error_callback=tool_error_as_result)
        sessions = InMemorySessionService()
        sess = await sessions.create_session(app_name="odie_writer", user_id=s.user_id)
        app = App(name="odie_writer", root_agent=agent, context_cache_config=CACHE)
        runner = Runner(app=app, session_service=sessions)
        out: list[str] = []
        capped = RunConfig(max_llm_calls=max_llm_calls)

        async def send(text: str) -> None:
            message = types.Content(role="user", parts=[types.Part(text=text)])
            async for ev in runner.run_async(user_id=s.user_id, session_id=sess.id, new_message=message,
                                             run_config=capped):
                if ev.content and ev.content.parts and not getattr(ev, "partial", False):
                    out.extend(p.text for p in ev.content.parts if p.text and not getattr(p, "thought", False))

        async def go():
            await send(f"It is {now} ({s.timezone}).\n\n{prompt}")
            if follow_up is None:
                return
            more = follow_up()
            if more is not None:
                await send(more)

        await asyncio.wait_for(go(), timeout)
        return "\n".join(out)

    async def tracker_notify(self, row: dict, summary: str, push: str | None = None, private_site: str | None = None) -> None:
        """A tracker found something: a line in Chat and a push to the phone. `push`: what the lock screen says instead of
        the summary (a signed-in tracker's details stay in the app); `private_site`: the chat line came from that
        signed-in site, so today's chat is private for it, as if the user had read the page there."""
        await self.post_message(f"🔔 {row['title']}: {summary}")
        if private_site:
            from odie.signin import guard as signin_guard
            signin_guard.remember(self.store, self.current_session_id(datetime.now(self.tz).strftime("%Y-%m-%d")), private_site)
        try:
            send_to_all(self.store, row["title"], (push or summary)[:160], url="/#today", tag=f"tracker-{row['id']}")
        except Exception:  # noqa: BLE001
            log.warning("tracker push failed", exc_info=True)

    async def run_trackers(self) -> int:
        from datetime import UTC

        from odie import trackers
        return await trackers.run_due(self.store, self.background_turn, self.tracker_notify, datetime.now(UTC), self.tz)

    async def notify(self, text: str, task_id: int, media: list[dict] | None = None) -> None:
        """A reminder that just fired, raised to every open app as a notice (not a chat message): the curtain shows it,
        and only Act (routes: /reminders/{id}/act) posts it into the chat."""
        await self.bus.publish({"type": "reminder", "id": task_id, "text": text, "ts": time.time(), **({"media": media} if media else {})})

    async def post_message(self, text: str, session_id: str | None = None, media: list[dict] | None = None) -> Event:
        """A message from Odie that did not come from a user turn (reminder, 'done as you asked', summary). `media`
        (a spoken reminder's memo) rides in the event's metadata: shown in the chat, never seen by the model."""
        s = config.settings
        today = datetime.now(self.tz).strftime("%Y-%m-%d")
        sid = session_id or self.current_session_id(today)
        async with self.lock_for(sid):
            sid = await self._ensure_session(sid)
            sess = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=sid)
            ev = Event(author="odie", invocation_id=f"odie-{uuid.uuid4().hex[:8]}",
                       content=types.Content(role="model", parts=[types.Part(text=text)]), timestamp=time.time(),
                       custom_metadata={"media": media} if media else None)
            await self.session_service.append_event(session=sess, event=ev)
        self.store.audit("agent", "message", result_summary=text, session_id=sid)
        await self.bus.publish({"type": "message", "text": text, "ts": ev.timestamp, "session_id": sid, **({"media": media} if media else {})})
        return ev

    @staticmethod
    def estimate_tokens(events: list[Any]) -> int:
        chars = 0
        for ev in events:
            for p in (ev.content.parts if ev.content and ev.content.parts else []):
                if p.text:
                    chars += len(p.text)
                elif p.function_call:
                    chars += len(str(p.function_call.args or "")) + 40
                elif p.function_response:
                    chars += min(len(str(p.function_response.response or "")), 160)
        return chars // 4

    @classmethod
    def context_tokens(cls, events: list[Any]) -> int:
        """Tokens the next model call will read: the last reply's real count from the model (system prompt, tools and
        conversation included) plus an estimate for anything appended since; the estimate alone before any reply."""
        for i in range(len(events) - 1, -1, -1):
            u = events[i].usage_metadata
            if u and u.total_token_count:
                return u.total_token_count + cls.estimate_tokens(events[i + 1:])
        return cls.estimate_tokens(events)

    async def refresh_history_limit(self) -> int:
        """Re-read the chosen model's context size and the history limit that follows from it (3/4, capped). Read
        again when the model changes, and every time for LM Studio (local, quick), whose loaded size can differ from
        its maximum."""
        sel = resolve_selection(self.store, "chat")
        key = model_key(sel)
        if key != self._limit_key or sel.provider.id == "lmstudio":
            self._limit_key = key
            self.history_limit = history_limit_for(await context_window(sel))
        return self.history_limit

    async def context_usage(self, date: str) -> dict[str, int]:
        """How full today's current segment is: the tokens the model read last time (after any cut) against the
        history limit, past which older turns go as words only."""
        s = config.settings
        await self.refresh_history_limit()
        sess = await self.session_service.get_session(app_name=s.app_name, user_id=s.user_id,
                                                      session_id=self.current_session_id(date))
        return {"used": self.context_tokens(sess.events) if sess else 0, "limit": self.history_limit}

    async def new_chat(self, date: str) -> str:
        """The user asked for a clean slate: continue in a new segment with nothing carried over."""
        sid = self.current_session_id(date)
        async with self.lock_for(sid):
            n = (int(sid.rsplit("-", 1)[1]) if sid.count("-") == 4 else 1) + 1
            new_sid = f"chat-{date}-{n}"
            self._set_segment(date, n)
        await self._ensure_session(new_sid)
        self.invalidate_prompt()
        await self.post_message(NEW_CHAT, session_id=new_sid)
        self.store.audit("user", "new_chat", result_summary=f"{sid} -> {new_sid}")
        return new_sid

    def _reserved_tool_names(self) -> dict[str, str]:
        """Tool names Odie already has, which an MCP server may not shadow (ADK keeps the last one registered)."""
        names = {n: "Odie" for n in (*GATED_TOOLS, *addons.tool_names())}
        for t in self.agent.tools:
            if not getattr(t, "_odie_plugin", False) and getattr(t, "name", None):
                names[t.name] = "Odie"
        for n in ("load_skill", "unload_skill", "load_skill_resource", "list_skills", "adk_request_confirmation"):
            names[n] = "Odie"
        return names

    def _all_tool_names(self) -> dict[str, str]:
        """Every tool name in use: Odie's own, each loaded skill's and each app's. A new skill's tools may not reuse one."""
        names = self._reserved_tool_names()
        for e in self.plugins.get("skills", []):
            names.update({t: f"the {e.name} skill" for t in e.tools})
        for e in self.plugins.get("servers", []):
            names.update({t["name"] if isinstance(t, dict) else str(t): f"the {e.name} app" for t in getattr(e, "tools", [])})
        return names

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _close_later(self, toolsets: list, delay: float) -> None:
        await asyncio.sleep(delay)
        for t in toolsets:
            try:
                await t.close()
            except Exception:  # noqa: BLE001
                log.warning("closing an old plugin toolset failed", exc_info=True)

    async def _retry_later(self) -> None:
        await asyncio.sleep(self.retry_every)
        await self.load_plugins()

    async def load_plugins(self) -> dict:
        """(Re)build what the user can plug in: skills and MCP servers. One reload runs at a time. The new tool
        list is built in full, then swapped in with one assignment; ADK picks it up at the turn's next step.
        Old connections stay open for close_grace seconds, for a call already in flight. A server that failed
        (the vault not up yet at boot) is retried in the background. Never raises."""
        from google.adk.tools.skill_toolset import SkillToolset

        from odie.plugins.mcp import load_servers
        from odie.skills import build_skill_toolset
        from odie.skills.registry import discover
        async with self._plugins_lock:
            try:
                skills = discover(self.store)
                reserved = self._reserved_tool_names()
                for e in skills:
                    if e.status == "ok":
                        reserved.update({t: f"the {e.name} skill" for t in e.tools})
                servers = await load_servers(reserved=reserved)
                ok = [e for e in servers if e.status == "ok"]
                skill_ts = build_skill_toolset(skills, extra_skills=[e.skill for e in ok if e.skill],
                                               extra_tools=[e.toolset for e in ok if e.skill])
            except Exception:  # noqa: BLE001
                log.warning("loading plugins failed", exc_info=True)
                return self.plugins
            pinned = [e.toolset for e in ok if not e.skill]
            for t in (skill_ts, *pinned):
                t._odie_plugin = True
            old = [t for t in self.agent.tools if getattr(t, "_odie_plugin", False) or isinstance(t, SkillToolset)]
            old_connections = self._plugin_toolsets
            self.agent.tools = [*(t for t in self.agent.tools if t not in old), skill_ts, *pinned]
            self._plugin_toolsets = [e.toolset for e in ok]
            self._spawn(self._close_later([*old, *old_connections], self.close_grace))
            self.plugins = {"skills": skills, "servers": servers}
            self.invalidate_prompt()
            failed = any(e.status == "failed" for e in servers)
            self._retries_left = self._retries_left - 1 if failed else 8
            if failed and self._retries_left > 0:
                self._spawn(self._retry_later())
            return self.plugins

    async def reload_addon_tools(self, name: str) -> None:
        """Rebuild one add-on's tools (after its login changed, say), swap them in, and close the old ones so a
        connection with the old credentials doesn't linger."""
        addon = next((a for a in addons.active() if a.name == name), None)
        if addon is None:
            return
        tools = list(self.agent.tools)
        old = [t for t in tools if getattr(t, "_odie_addon", None) == name]
        at = tools.index(old[0]) if old else len(tools)  # in the same place, so the model sees the tools in the same order
        kept = [t for t in tools if t not in old]
        self.agent.tools = kept[:at] + addons.tools_of(addon, self.store) + kept[at:]
        for t in old:
            close = getattr(t, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                log.warning("closing an old %s tool failed", name, exc_info=True)

    async def close(self) -> None:
        for task in list(self._background):
            task.cancel()
        for t in self._plugin_toolsets:
            try:
                await t.close()
            except Exception:  # noqa: BLE001
                log.warning("closing a plugin toolset failed", exc_info=True)
        await self.runner.close()
