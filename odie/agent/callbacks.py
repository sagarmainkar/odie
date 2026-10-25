"""ADK plugin: audits every tool call, and fences other people's text (add-ons name those tools) before the model reads it."""
from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.plugins import BasePlugin

from odie.agent.compaction import turn_start  # noqa: F401 (earlier turns' shape lives there; named here for callers)
from odie.agent.context import session_id_of
from odie.store.db import Store

OPEN, CLOSE = "<<<UNTRUSTED EMAIL>>>", "<<<END UNTRUSTED EMAIL>>>"
CLAMP = {"search_everything": 3500, "search_notes": 3500, "read_note": 6000}
APP_RESULT_LIMIT = 40_000  # characters of one connected app's result the model sees (about 10k tokens)


def wrap_untrusted(text: str) -> str:
    """Fence third-party text. Marker strings inside the body are defanged so a sender cannot close the fence."""
    if text.startswith(OPEN) and text.endswith(CLOSE):
        return text
    body = text.replace(CLOSE, "[marker removed]").replace(OPEN, "[marker removed]")
    return f"{OPEN}\n{body}\n{CLOSE}"


def fence_tool_result(result: Any) -> Any:
    """Wrap every text payload in a tool result, whatever shape it arrived in:
    ADK 2.10 McpTool -> dumped CallToolResult {"content": [{"type": "text", "text": ...}], "structuredContent": ...};
    FunctionTool -> {"result": str} or a bare str."""
    if isinstance(result, str):
        return wrap_untrusted(result)
    if not isinstance(result, dict):
        return result
    out = dict(result)
    if isinstance(out.get("content"), list):
        out["content"] = [({**c, "text": wrap_untrusted(c["text"])} if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str) else c)
                          for c in out["content"]]
    if isinstance(out.get("structuredContent"), dict):
        out["structuredContent"] = {k: (wrap_untrusted(v) if isinstance(v, str) else v) for k, v in out["structuredContent"].items()}
    if isinstance(out.get("result"), str):
        out["result"] = wrap_untrusted(out["result"])
    return out


RAW_KEYS = {"raw", "_raw", "raw_data", "raw_payload"}  # a service's unparsed copy of what its other fields already say


def _shorten_fields(value: Any, keep: int, items: int | None = None, raw: bool = True) -> Any:
    """Every string in parsed JSON cut to `keep` characters (an email's HTML, an attachment's data), every list to its
    first `items` (with a count of the rest), and, raw=False, the raw copies left out; the rest kept."""
    if isinstance(value, str) and len(value) > keep:
        return value[:keep] + f"…[{len(value) - keep:,} more characters]"
    if isinstance(value, list):
        out = [_shorten_fields(v, keep, items, raw) for v in value[:items]]
        return out + ([f"…[{len(value) - items} more items: ask for fewer or narrow the search]"] if items and len(value) > items else [])
    if isinstance(value, dict):
        return {k: (_shorten_fields(v, keep, items, raw) if raw or k.lower() not in RAW_KEYS else "[raw copy left out]")
                for k, v in value.items()}
    return value


def _fit_json(text: str, limit: int) -> str:
    """JSON text over the limit with its long fields shortened, step by step, until it fits: every item and its short
    fields (a subject, a sender, a date) survive, where a plain cut would keep only the first item."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    for keep, items, raw in ((2000, None, True), (2000, None, False), (800, None, False), (800, 25, False), (300, 25, False),
                             (300, 10, False), (100, 10, False)):
        out = json.dumps(_shorten_fields(data, keep, items, raw), ensure_ascii=False)
        if len(out) <= limit:
            return out
    return out


def background_after_tool(plugin: "OdiePlugin"):
    """An after_tool_callback for a background turn (a tracker, the watch): the same cuts, fencing and audit as chat's,
    so a connected app's 11 MB answer never floods a background model either."""
    async def after(tool, args, tool_context, tool_response):
        return await plugin.after_tool_callback(tool=tool, tool_args=args or {}, tool_context=tool_context, result=tool_response)
    return after


def cut_app_result(result: Any, limit: int = APP_RESULT_LIMIT) -> Any:
    """A connected app's result over the limit, cut to it, with a note so the model asks for less next time."""
    if not (isinstance(result, dict) and isinstance(result.get("content"), list)):
        return result
    size = sum(len(c["text"]) for c in result["content"] if isinstance(c, dict) and isinstance(c.get("text"), str))
    if size <= limit:
        return result
    result = {**result, "content": [({**c, "text": _fit_json(c["text"], limit)} if isinstance(c, dict) and isinstance(c.get("text"), str)
                                     and len(c["text"]) > limit else c) for c in result["content"]]}
    note = (f"\n[cut: the full result was {size:,} characters, too much to read at once. Ask for less: a narrower "
            "search, fewer results, or only the fields you need.]")
    out, left = dict(result), limit
    content = []
    for c in result["content"]:
        if isinstance(c, dict) and isinstance(c.get("text"), str):
            if left <= 0:
                continue  # past the limit: later text parts go
            c = {**c, "text": c["text"][:left]}
            left -= len(c["text"])
        content.append(c)
    last = max((i for i, c in enumerate(content) if isinstance(c, dict) and isinstance(c.get("text"), str)), default=None)
    if last is not None:
        content[last] = {**content[last], "text": content[last]["text"] + note}
    out["content"] = content
    out.pop("structuredContent", None)  # the same data again, uncut
    return out


def clamp_tool_result(result: Any, limit: int) -> Any:
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        out = dict(result)
        out["content"] = [({**c, "text": c["text"][: limit - 1] + "…"} if isinstance(c, dict) and isinstance(c.get("text"), str) and len(c["text"]) > limit else c)
                          for c in out["content"]]
        return out
    if isinstance(result, str) and len(result) > limit:
        return result[: limit - 1] + "…"
    return result


def _summarise(result: Any) -> str:
    s = result if isinstance(result, str) else json.dumps(result, default=str)
    return s[:200]


def _awaiting_tap(result: Any) -> bool:
    return isinstance(result, dict) and "requires confirmation" in str(result.get("error", ""))


def _drop_duplicate_structured(result: Any) -> Any:
    """An MCP result carries its data twice (text content and structuredContent); the model needs it once."""
    if isinstance(result, dict) and result.get("structuredContent") is not None and isinstance(result.get("content"), list) \
            and any(isinstance(c, dict) and c.get("type") == "text" and c.get("text") for c in result["content"]):
        return {k: v for k, v in result.items() if k != "structuredContent"}
    return result


def _tool_fields(tool) -> set[str] | None:
    """The argument names a tool declares; None when it doesn't say or accepts any field."""
    try:
        d = tool._get_declaration()
    except Exception:  # noqa: BLE001
        return None
    if d is None:
        return None
    schema = getattr(d, "parameters_json_schema", None)
    if isinstance(schema, dict):
        if schema.get("additionalProperties") not in (None, False):
            return None
        return set((schema.get("properties") or {}).keys()) or None
    params = getattr(d, "parameters", None)
    props = getattr(params, "properties", None) if params is not None else None
    return set(props.keys()) if props else None


def _close_skills(result: Any, asked: str) -> Any:
    """A skill name that doesn't exist (mcp-zapier for mcp-zapier-2): the names like it, so the model loads the right
    one instead of giving up."""
    if not (isinstance(result, dict) and result.get("error_code") == "SKILL_NOT_FOUND"):
        return result
    import difflib

    from odie.plugins.mcp import TOOL_SKILL
    names = set(TOOL_SKILL.values())
    try:
        from odie.about import hooks
        names |= {e.name for e in (getattr(hooks.get("runner"), "plugins", None) or {}).get("skills", [])}
    except Exception:  # noqa: BLE001 (a hint, never a failure)
        pass
    close = [n for n in sorted(names) if asked and (n.startswith(asked) or asked.startswith(n))]
    close += [n for n in difflib.get_close_matches(asked, sorted(names), n=3, cutoff=0.6) if n not in close]
    if not close:
        return result
    return {**result, "error": f"{result.get('error', 'No such skill.')} Skills with names like it: {', '.join(close[:3])}."}


SKILL_STAYS = ("These instructions stay in this conversation: use them for questions this skill is for, without loading it "
               "again, and leave them aside for other questions.")


def _skill_stays(result: Any) -> Any:
    """A loaded skill's instructions, with a note that they stay. They're a tool result that stays in the conversation
    as sent (odie.agent.compaction), so a later question about the same thing needn't load the skill again, and one
    about something else shouldn't be answered through it (Gemma did that on 8 Oct, when skills lingered).
      {"skill_name": "trackers", "instructions": "…"} -> the same plus "note": SKILL_STAYS
      {"error": "Skill 'x' not found."}               -> unchanged"""
    if not (isinstance(result, dict) and "instructions" in result):
        return result
    return {**result, "note": SKILL_STAYS}


def fix_tool_args(tool, args: dict) -> str | None:
    """Models sometimes glue a value onto its field name ("subject NEFT Payment…": "") instead of
    subject="NEFT Payment…". Put such values back in place. Any field the tool still doesn't have gets a plain
    message naming the fields it does have, so the model can correct the call instead of retrying it blindly."""
    fields = _tool_fields(tool)
    if not fields or not isinstance(args, dict):
        return None
    for key in [k for k in args if k not in fields]:
        value = args[key]
        for f in sorted(fields, key=len, reverse=True):  # longest first: reply_to_message_id before reply
            if key.startswith(f) and len(key) > len(f) and key[len(f)] in " :=\t" and value in ("", None) and not args.get(f):
                args[f] = key[len(f):].strip(" :=\t\"'")
                del args[key]
                break
    unknown = [k for k in args if k not in fields]
    if not unknown:
        return None
    names = ", ".join(fields_in_order(tool, fields))
    return (f"Not run: this tool has no field named {', '.join(repr(k) for k in unknown)}. Its fields are: {names}. "
            "Call it again with those exact field names, each with its own value.")


def fields_in_order(tool, fields: set[str]) -> list[str]:
    try:
        schema = tool._get_declaration().parameters_json_schema or {}
        order = list((schema.get("properties") or {}).keys())
    except Exception:  # noqa: BLE001
        order = []
    return [f for f in order if f in fields] + sorted(fields - set(order))


class OdiePlugin(BasePlugin):
    def __init__(self, store: Store):
        super().__init__(name="odie")
        self.store = store

    async def after_tool_callback(self, *, tool, tool_args: dict[str, Any], tool_context, result: Any) -> Any | None:
        session_id = session_id_of(tool_context)
        inv = getattr(tool_context, "invocation_id", None)
        if _awaiting_tap(result):
            return None  # a gated tool paused for its approval card: it hasn't run, so it isn't a tool call yet
        from odie.agent import confidential, turn
        if tool.name == "browser_type" and turn.private_sites():  # typing in a signed-in turn: its length, never its text
            tool_args = {**tool_args, "text": f"({len(str(tool_args.get('text', '')))} characters)"}
        exposed = confidential.label_for(tool.name)  # the user's mail, notes, memory: from here the chat asks before words leave
        if exposed is not None and turn.mark_read(exposed):
            from odie.signin import guard as signin_guard
            signin_guard.remember_read(self.store, session_id, exposed)
        self.store.audit("agent", "tool_call", tool=tool.name, args=tool_args, result_summary=_summarise(result),
                         session_id=session_id, invocation_id=inv)
        from odie import addons
        addons.call("after_tool", tool.name, tool_args, result, self.store, session_id, inv)  # e.g. provenance for cards
        out = _drop_duplicate_structured(result)
        if tool.name == "load_skill":
            out = _close_skills(out, str((tool_args or {}).get("skill_name") or ""))
            out = _skill_stays(out)
        limit = CLAMP.get(tool.name) or addons.clamps().get(tool.name)
        if limit:
            out = clamp_tool_result(out, limit)
        else:
            from odie.plugins.mcp import TOOL_APP
            if tool.name in TOOL_APP:
                out = cut_app_result(out)
        if tool.name in addons.untrusted_tools():
            out = fence_tool_result(out)
        return None if out is result else out

    async def on_tool_error_callback(self, *, tool, tool_args: dict[str, Any], tool_context, error: Exception) -> dict | None:
        """An app's tool called before its skill was loaded: say which skill, so the model loads it and goes on (a bare
        "no tool with that name" made it tell the user the app had dropped off)."""
        from odie.plugins.mcp import TOOL_APP, TOOL_SKILL
        skill = TOOL_SKILL.get(tool.name)
        if skill is None or "not found" not in str(error).lower():
            return None
        return {"error": f"{tool.name} is one of {TOOL_APP.get(tool.name, 'a connected app')}'s tools, and they load with "
                         f"their skill: call load_skill(\"{skill}\") first, then call {tool.name} again."}

    async def before_tool_callback(self, *, tool, tool_args: dict[str, Any], tool_context) -> dict | None:
        problem = fix_tool_args(tool, tool_args)
        if problem:
            session_id = session_id_of(tool_context)
            self.store.audit("agent", "tool_args_rejected", tool=tool.name, result_summary=problem[:200], session_id=session_id)
            return {"error": problem}
        return None

    async def after_model_callback(self, *, callback_context, llm_response):
        """Keep each reply's input and cached token counts, whichever provider answered (odie.agent.usage)."""
        from odie.agent import usage
        try:
            usage.record(self.store, getattr(llm_response, "usage_metadata", None), getattr(llm_response, "model_version", None))
        except Exception:  # noqa: BLE001 (bookkeeping must never break a turn)
            logging.getLogger("odie.usage").debug("usage not recorded", exc_info=True)
        return None

    async def before_model_callback(self, *, callback_context, llm_request):
        """Earlier turns go to the model exactly as they went before; once the conversation passes this chat's limit,
        everything before its last five turns goes as words only, in rare cuts (odie.agent.compaction), so every
        provider can reuse its prompt cache. Whether it has passed is read from the model's own counts on the
        session's events (the number the chat's ring shows) where there are any, else from the characters."""
        if llm_request.contents:
            from odie.agent import compaction, turn
            limit_tokens = turn.HISTORY_LIMIT.get() or compaction.DEFAULT_LIMIT_TOKENS
            session = getattr(callback_context, "session", None)
            events = getattr(session, "events", None) or []
            counts = compaction.counted_before(events) if events else None
            llm_request.contents = compaction.compact(list(llm_request.contents), compaction.compact_at(limit_tokens),
                                                      counts=counts, limit_tokens=limit_tokens)
        self._budget(getattr(callback_context, "invocation_id", None), llm_request)
        return None

    def _budget(self, inv: str | None, llm_request) -> None:
        """The turn's last steps: told to answer with what it has, and the very last one without tools, so a turn ends
        with an answer rather than "I stopped after 40 steps"."""
        from odie.app.runner import MAX_LLM_CALLS
        if inv is None:
            return
        calls = self.__dict__.setdefault("_calls", {})
        calls[inv] = n = calls.get(inv, 0) + 1
        if len(calls) > 50:
            calls.pop(next(iter(calls)))
        cfg = getattr(llm_request, "config", None)
        if n >= MAX_LLM_CALLS - 5 and cfg is not None:
            left = MAX_LLM_CALLS - n
            note = (f"\n\n[You have {left} step{'s' if left != 1 else ''} left in this turn: answer now with what you found, "
                    "and say what you couldn't find.]" if left else
                    "\n\n[This is the last step of the turn: no more tools. Answer now with what you found, and say what you couldn't find.]")
            if isinstance(cfg.system_instruction, str) or cfg.system_instruction is None:
                cfg.system_instruction = (cfg.system_instruction or "") + note
        if n >= MAX_LLM_CALLS and cfg is not None:
            cfg.tools = []
            if hasattr(llm_request, "tools_dict"):
                llm_request.tools_dict = {}
