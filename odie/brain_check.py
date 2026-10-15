"""The brain check: before a model becomes the brain, try it on what Odie needs from it, in about 30 seconds, and say
in plain words whether it will work. A tool call with three fields (three runs, two must be exactly right: broken chat
templates mangle these), using the tool's result in the next turn, speed, and the context size."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from odie.agent.model import complete
from odie.models import Selection, context_window
from odie.sampling import CHAT_TOP_P, CHECK_TEMPERATURE

TOOL = {"type": "function", "function": {
    "name": "save_reminder", "description": "Save a reminder for the user.",
    "parameters": {"type": "object", "properties": {
        "title": {"type": "string", "description": "What to remind them of"},
        "date": {"type": "string", "description": "The day, as YYYY-MM-DD"},
        "priority": {"type": "string", "enum": ["low", "normal", "high"]}}, "required": ["title", "date", "priority"]}}}
SYSTEM = ("You are a personal assistant. When the user asks for a reminder, call save_reminder; after it runs, tell them in "
          "two short sentences that it was saved, with its id, and when you'll remind them.")
REMINDERS = [("Priya", "2026-10-09", "high"), ("Ravi", "2026-11-02", "low"), ("Meera", "2026-12-15", "normal")]
RESULT = {"saved": True, "id": "R-417"}
FIELDS = {"title", "date", "priority"}
MAX_TOKENS = 2000  # room for a thinking model; a model that doesn't think stops long before
SAMPLING = {"max_tokens": MAX_TOKENS, "temperature": CHECK_TEMPERATURE, "top_p": CHAT_TOP_P}  # as chat runs by default; litellm
                                                                                              # drops what a model refuses
SLOW = 8          # tokens a second below this: replies will feel slow
FAST = 20
TOO_SMALL = 16_000
SMALL = 32_000
_NO_TOOLS = re.compile(r"(does not|doesn't) support tools|tools? (use )?(is|are) not supported|no tool support", re.I)
_THINK = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|$)", re.S)


@dataclass(frozen=True)
class Part:
    name: str           # "tools" | "result" | "speed" | "context"
    status: str         # "pass" | "warn" | "fail" | "unknown"
    detail: str


@dataclass(frozen=True)
class Report:
    provider: str
    model: str
    verdict: str        # "good" | "slow" | "warn" | "fail"
    sentence: str
    parts: tuple[Part, ...]
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))


class _Failed(Exception):
    """A request that didn't get an answer: the reason, in plain words."""


class _NoTools(_Failed):
    """The provider says this model can't take tools at all."""


def _ask(i: int) -> tuple[str, tuple[str, str, str]]:
    name, date, prio = REMINDERS[i % len(REMINDERS)]
    return f"Remind me to call {name} on {date}, {prio} priority.", (name, date, prio)


def _right(call: dict, expected: tuple[str, str, str]) -> bool:
    fn = call.get("function") or {}
    if fn.get("name") != "save_reminder":
        return False
    raw = fn.get("arguments")
    try:
        args = json.loads(raw or "{}") if isinstance(raw, str) else raw or {}
    except ValueError:
        return False
    name, date, prio = expected
    return (isinstance(args, dict) and set(args) == FIELDS and args.get("date") == date
            and str(args.get("priority", "")).lower() == prio and name.lower() in str(args.get("title", "")).lower())


def _said(error: Exception) -> str:
    """What a provider's error says, in its own words. litellm wraps them, e.g. "OpenAIException - Error code: 400 -
    {'error': {'message': 'model not loaded', 'type': 'api_error'}}": the message inside when there is one, else the text
    without litellm's prefix and the JSON punctuation.
      ...{'error': {'message': 'does not support tools'}}  -> "does not support tools"
      ...Error code: 500 - {'error': 'model not loaded'}   -> "Error code: 500 - 'error': 'model not loaded'" """
    text = str(error)
    m = re.search(r"['\"]message['\"]:\s*['\"]([^'\"]{1,200})", text)
    if m:
        return m.group(1).strip()
    text = re.sub(r"^.*?Exception - ", "", text, count=1, flags=re.S)
    return re.sub(r"[{}\[\]]", "", text)[:200].strip()


async def check(sel: Selection, transport=None, runs: int = 3, clock: Callable[[], float] = time.monotonic) -> Report:
    p = sel.provider

    async def ask(messages: list[dict]) -> dict:
        """One request through litellm (odie.agent.model.complete); the reply in OpenAI's shape as a plain dict, or
        _Failed with the reason in plain words."""
        import litellm
        try:
            reply = await complete(sel, messages, tools=[TOOL], tool_choice="auto", timeout=60, transport=transport, **SAMPLING)
        except litellm.exceptions.Timeout:
            raise _Failed(f"{p.name} took too long to answer") from None
        except litellm.exceptions.APIConnectionError:
            raise _Failed(f"couldn't reach {p.name}") from None
        except Exception as e:  # noqa: BLE001 (litellm's other errors: what the provider said, with its status)
            said = _said(e)
            if _NO_TOOLS.search(said):
                raise _NoTools(said) from None
            status = getattr(e, "status_code", None)
            raise _Failed(f"{p.name} said {status}: {said}" if status else f"{p.name}: {said}") from None
        return reply.model_dump()

    parts: dict[str, Part] = {}
    error = ""
    good: tuple[list[dict], dict] | None = None
    right, out_of_room = 0, 0
    try:
        for i in range(runs):
            text, expected = _ask(i)
            messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
            choice = (await ask(messages)).get("choices") or [{}]
            msg = choice[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            if len(calls) == 1 and _right(calls[0], expected):
                right += 1
                good = good or (messages, calls[0])
            elif not calls and choice[0].get("finish_reason") == "length":
                out_of_room += 1
        need = max(1, runs - 1)
        detail = f"{right} of {runs} calls had the right fields and values"
        if out_of_room:
            detail += f"; {out_of_room} ran out of room while thinking"
        parts["tools"] = Part("tools", "pass" if right >= need else "fail", detail)
    except _NoTools:
        parts["tools"] = Part("tools", "fail", "the model doesn't support tool calls")
        error = "no tools"
    except _Failed as e:
        error = str(e)
        parts["tools"] = Part("tools", "fail", error)
    if good is not None and not error:
        messages, call = good
        cid = call.get("id") or "call_1"
        follow = [*messages, {"role": "assistant", "content": None,
                              "tool_calls": [{"id": cid, "type": "function", "function": call["function"]}]},
                  {"role": "tool", "tool_call_id": cid, "content": json.dumps(RESULT)}]
        try:
            t0 = clock()
            d = await ask(follow)
            took = max(clock() - t0, 1e-3)
            choice = (d.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            text = _THINK.sub("", content if isinstance(content, str) else json.dumps(content))
            used = RESULT["id"] in text
            parts["result"] = Part("result", "pass" if used else "fail", "used the tool's result" if used else "didn't use the tool's result")
            rate = ((d.get("usage") or {}).get("completion_tokens") or max(1, len(text) // 4)) / took
            parts["speed"] = Part("speed", "pass" if rate >= SLOW else "warn", f"{rate:.0f} tokens a second")
        except _Failed as e:
            error = str(e)
            parts["result"] = Part("result", "fail", error)
    for name in ("result", "speed"):
        parts.setdefault(name, Part(name, "unknown", "not checked"))
    window = None if error else await context_window(sel)
    if window is None:
        parts["context"] = Part("context", "unknown", "context unknown")
    else:
        k = window // 1024
        parts["context"] = Part("context", "fail" if window < TOO_SMALL else "warn" if window < SMALL else "pass", f"{k}K tokens of context")
    return _report(sel, parts, error)


def _report(sel: Selection, parts: dict[str, Part], error: str) -> Report:
    ordered = tuple(parts[n] for n in ("tools", "result", "speed", "context"))
    name = sel.model
    if error == "no tools":
        return Report(sel.provider.id, sel.model, "fail", f"{name}: This model doesn't support tool calls. Pick another or use a cloud key.", ordered)
    if error:
        return Report(sel.provider.id, sel.model, "fail", f"{name}: Couldn't check it: {error.rstrip('.')}.", ordered)
    if parts["tools"].status == "fail":
        return Report(sel.provider.id, sel.model, "fail", f"{name}: This model mangles tool calls. Pick another or use a cloud key.", ordered)
    if parts["result"].status == "fail":
        return Report(sel.provider.id, sel.model, "fail", f"{name}: This model ignores tool results. Pick another or use a cloud key.", ordered)
    if parts["context"].status == "fail":
        return Report(sel.provider.id, sel.model, "fail", f"{name}: Its context is too small ({parts['context'].detail.split()[0]}; Odie needs 16K).", ordered)
    bits = ["uses tools correctly"]
    rate = parts["speed"].detail.split()[0] if parts["speed"].status != "unknown" else ""
    if parts["speed"].status == "warn":
        bits.append(f"slow ({rate} tokens a second): replies will feel slow")
        verdict = "slow"
    else:
        bits.append("fast" if rate and int(rate) >= FAST else "quick enough")
        verdict = "good"
    if parts["context"].status == "warn":
        bits.append(f"small context ({parts['context'].detail.split()[0]}): long chats are summarised sooner")
        verdict = "warn" if verdict == "good" else verdict
    bits.append("good choice" if verdict == "good" else "usable")
    return Report(sel.provider.id, sel.model, verdict, f"{name}: " + " · ".join(bits), ordered)
