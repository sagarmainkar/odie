"""The brain check: a model is tried on a tool call (three runs), on using the tool's result, for speed and for context
size, and the answer is one plain sentence. Each test plays a model behind httpx.MockTransport, which the check's litellm
call is routed through (odie.agent.model.complete)."""
import json
from dataclasses import asdict

import httpx
import pytest

from odie import brain_check
from odie.models import Provider, Selection

GOOD_ARGS = {"title": "Call Priya", "date": "2026-10-09", "priority": "high"}


def _sel(key=None):
    return Selection(Provider("ollama", "Ollama", "http://localhost:11434/v1", key, True), "glm-test", "chat")


def _call(args):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "save_reminder", "arguments": json.dumps(args)}}]}}],
            "usage": {"completion_tokens": 20}}


def _say(text, tokens=40, **extra):
    return {"choices": [{"message": {"role": "assistant", "content": text, **extra}}], "usage": {"completion_tokens": tokens}}


def _asked(body):
    """The reminder this run asks for: (name, date, priority), read from the user's message."""
    import re
    m = re.search(r"call (\w+) on (\d{4}-\d{2}-\d{2}), (\w+) priority", body["messages"][1]["content"])
    return m.groups()


def model(calls=None, reply=None, status=200, tokens=40, seen=None, body_error=None, finish=None, stats=None, ids=True, **extra):
    """A fake chat model. calls[n] for the n-th tool run: "right" answers that run's reminder correctly, a dict gives
    those arguments, a string answers in text. A turn with a tool result answers reply (default: names the id)."""
    runs = {"n": 0}
    calls = calls or ["right"] * 3

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append((request, body))
        if status != 200:
            return httpx.Response(status, json=body_error if body_error is not None else {"error": "model not loaded"})
        if body["messages"][-1]["role"] == "tool":
            out = _say(reply if reply is not None else "Saved it as R-417. I'll remind you on the day.", tokens, **extra)
            if stats:
                out["stats"] = stats
            return httpx.Response(200, json=out)
        name, date, prio = _asked(body)
        c = calls[min(runs["n"], len(calls) - 1)]
        runs["n"] += 1
        if finish == "length":
            return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "<think>hmm"}}]})
        if c == "right":
            out = _call({"title": f"Call {name}", "date": date, "priority": prio})
        else:
            out = _call(c) if isinstance(c, dict) else _say(c)
        if not ids:
            out["choices"][0]["message"]["tool_calls"][0].pop("id")
        return httpx.Response(200, json=out)
    return httpx.MockTransport(handler)


class Clock:
    """Each request takes `step` seconds."""
    def __init__(self, step=0.5):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step / 2
        return self.t


@pytest.fixture(autouse=True)
def context(monkeypatch):
    async def window(sel, transport=None):
        return 128_000
    monkeypatch.setattr(brain_check, "context_window", window)


def _parts(r):
    return {p.name: p.status for p in r.parts}


async def test_a_good_model_passes_every_part():
    r = await brain_check.check(_sel(), transport=model(), clock=Clock())
    assert _parts(r) == {"tools": "pass", "result": "pass", "speed": "pass", "context": "pass"}
    assert r.verdict == "good" and "uses tools correctly" in r.sentence and "good choice" in r.sentence


async def test_wrong_fields_fail_the_tool_part():
    wrong = {"title": "Call Priya", "when": "2026-10-09", "priority": "high"}
    r = await brain_check.check(_sel(), transport=model([wrong] * 3), clock=Clock())
    assert _parts(r)["tools"] == "fail" and r.verdict == "fail"
    assert r.sentence.endswith("This model mangles tool calls. Pick another or use a cloud key.")


async def test_text_instead_of_a_call_fails():
    r = await brain_check.check(_sel(), transport=model([json.dumps(GOOD_ARGS)] * 3), clock=Clock())
    assert _parts(r)["tools"] == "fail" and "0 of 3" in next(p.detail for p in r.parts if p.name == "tools")


async def test_two_of_three_is_enough():
    bad = {"title": "Call Priya", "date": "9 Oct", "priority": "high"}
    r = await brain_check.check(_sel(), transport=model(["right", bad, "right"]), clock=Clock())
    assert _parts(r)["tools"] == "pass" and "2 of 3" in next(p.detail for p in r.parts if p.name == "tools")
    r = await brain_check.check(_sel(), transport=model(["right", bad, bad]), clock=Clock())
    assert _parts(r)["tools"] == "fail"


async def test_ignoring_the_result_fails():
    r = await brain_check.check(_sel(), transport=model(reply="Done, all set."), clock=Clock())
    assert _parts(r)["result"] == "fail" and r.verdict == "fail" and "ignores tool results" in r.sentence


async def test_slow_is_a_warning_not_a_failure():
    r = await brain_check.check(_sel(), transport=model(tokens=12), clock=Clock(step=4.0))
    assert _parts(r)["speed"] == "warn" and r.verdict == "slow" and "slow" in r.sentence
    assert "tokens a second" in next(p.detail for p in r.parts if p.name == "speed")


async def test_small_context_fails_and_medium_warns(monkeypatch):
    async def small(sel, transport=None):
        return 8_192
    monkeypatch.setattr(brain_check, "context_window", small)
    r = await brain_check.check(_sel(), transport=model(), clock=Clock())
    assert _parts(r)["context"] == "fail" and r.verdict == "fail" and "16K" in r.sentence

    async def medium(sel, transport=None):
        return 24_576
    monkeypatch.setattr(brain_check, "context_window", medium)
    r = await brain_check.check(_sel(), transport=model(), clock=Clock())
    assert _parts(r)["context"] == "warn" and r.verdict == "warn"


async def test_unknown_context_doesnt_decide(monkeypatch):
    async def unknown(sel, transport=None):
        return None
    monkeypatch.setattr(brain_check, "context_window", unknown)
    r = await brain_check.check(_sel(), transport=model(), clock=Clock())
    assert _parts(r)["context"] == "unknown" and r.verdict == "good"
    assert "context unknown" in next(p.detail for p in r.parts if p.name == "context")


async def test_a_provider_error_is_a_plain_failure():
    r = await brain_check.check(_sel(), transport=model(status=500), clock=Clock())
    assert _parts(r)["tools"] == "fail" and _parts(r)["result"] == "unknown" and r.verdict == "fail"
    assert r.sentence.startswith("glm-test: Couldn't check it:") and "500" in r.sentence

    def down(request):
        raise httpx.ConnectError("refused")
    r = await brain_check.check(_sel(), transport=httpx.MockTransport(down), clock=Clock())
    assert r.verdict == "fail" and "Couldn't check it" in r.sentence


async def test_thinking_output_is_ignored():
    r = await brain_check.check(_sel(), transport=model(reply="<think>the id is in the result</think>Saved as R-417.",
                                                        reasoning_content="Let me look at the result."), clock=Clock())
    assert _parts(r)["result"] == "pass"
    r = await brain_check.check(_sel(), transport=model(reply="<think>R-417 is the id</think>Done."), clock=Clock())
    assert _parts(r)["result"] == "fail"  # mentioning it only while thinking doesn't count


async def test_the_key_is_sent_but_never_kept():
    seen = []
    r = await brain_check.check(_sel(key="sk-secretvalue123"), transport=model(seen=seen), clock=Clock())
    assert all(req.headers["authorization"] == "Bearer sk-secretvalue123" for req, _ in seen)
    assert "sk-secretvalue123" not in json.dumps(asdict(r))



async def test_each_run_is_a_different_reminder_at_the_chats_sampling():
    seen = []
    await brain_check.check(_sel(), transport=model(seen=seen), clock=Clock())
    asks = [b["messages"][1]["content"] for _, b in seen if b["messages"][-1]["role"] == "user"]
    assert len(set(asks)) == 3
    assert all(b.get("temperature") == 0.7 and b.get("reasoning_effort") == "low" for _, b in seen)  # the same word every model gets
    copied = {"title": "Call Priya", "date": "2026-10-09", "priority": "high"}
    r = await brain_check.check(_sel(), transport=model(["right", copied, copied]), clock=Clock())
    assert _parts(r)["tools"] == "fail"  # the first run's answer isn't right for the others


async def test_no_tool_support_is_said_plainly():
    err = {"error": {"message": "registry.ollama.ai/library/gemma3:latest does not support tools", "type": "api_error"}}
    r = await brain_check.check(_sel(), transport=model(status=400, body_error=err), clock=Clock())
    assert r.verdict == "fail" and r.sentence.endswith("This model doesn't support tool calls. Pick another or use a cloud key.")
    assert "{" not in r.sentence


async def test_a_json_error_body_is_said_plainly():
    r = await brain_check.check(_sel(), transport=model(status=500, body_error={"error": {"message": "model not loaded"}}), clock=Clock())
    assert "model not loaded" in r.sentence and "{" not in r.sentence


async def test_thinking_that_runs_out_of_room():
    r = await brain_check.check(_sel(), transport=model(finish="length"), clock=Clock())
    assert _parts(r)["tools"] == "fail" and "ran out of room" in next(p.detail for p in r.parts if p.name == "tools")


async def test_a_missing_tool_call_id_is_filled_in():
    seen = []
    await brain_check.check(_sel(), transport=model(seen=seen, ids=False), clock=Clock())
    follow = next(b for _, b in seen if b["messages"][-1]["role"] == "tool")
    sent_id = follow["messages"][2]["tool_calls"][0]["id"]
    assert sent_id and follow["messages"][-1]["tool_call_id"] == sent_id


async def test_the_check_goes_through_litellm_like_every_other_call():
    """The fake server is reached through litellm (the check carries the key as a Bearer header and the effort word), so
    what works here works in the chat: litellm, not Odie, knows which parameters each model refuses."""
    seen = []
    r = await brain_check.check(_sel(key="sk-k"), transport=model(seen=seen), clock=Clock())
    assert r.verdict == "good"
    req, body = seen[0]
    assert req.headers["authorization"] == "Bearer sk-k" and req.url.path.endswith("/chat/completions")
    assert body["reasoning_effort"] == "low" and body["max_tokens"] == brain_check.MAX_TOKENS and "max_completion_tokens" not in body
