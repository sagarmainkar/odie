"""Keeping model calls to train a smaller model on (odie.agent.capture): off unless ODIE_CAPTURE=1, a streamed reply is
put back together, the long repeated parts are kept once, and images never go in."""
import dataclasses
import gzip
import json
from types import SimpleNamespace as NS

import pytest

from odie.agent import capture


@pytest.fixture
def kept(isolated_settings, monkeypatch, tmp_path):
    assert str(isolated_settings.data_dir) == str(tmp_path)  # never the real data folder
    capturing(monkeypatch)
    return tmp_path / "training"


def capturing(monkeypatch):
    from odie import config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, capture=True))


def lines(folder):
    out = []
    for day in folder.glob("*.jsonl.gz"):
        with gzip.open(day, "rt") as f:
            out += [json.loads(line) for line in f]
    return out


def test_off_by_default(isolated_settings):
    assert capture.on() is False


def test_a_call_is_kept_with_its_reply_and_the_prompt_kept_once(kept):
    system = {"role": "system", "content": "You are Odie. " * 500}
    for question in ("What's due?", "And tomorrow?"):
        capture.keep("openai/deepseek", [system, {"role": "user", "content": question}], [{"name": "task_add"}],
                     {"text": "Electricity.", "tool_calls": []})
    calls = lines(kept)
    assert [c["messages"][0]["content"] for c in calls] == ["What's due?", "And tomorrow?"]
    assert calls[0]["system"] == calls[1]["system"] and calls[0]["tools"] == calls[1]["tools"]
    assert len(list((kept / "parts").glob("*.json"))) == 2  # one system prompt, one tool list
    assert "You are Odie" in (kept / "parts" / f"{calls[0]['system']}.json").read_text()


def test_images_never_go_in(kept):
    picture = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}
    capture.keep("m", [picture], None, {"text": "", "tool_calls": []})
    assert lines(kept)[0]["messages"][0]["content"][0]["image_url"]["url"] == "[image omitted, 26 characters of base64]"
    assert picture["content"][0]["image_url"]["url"].startswith("data:")  # the call's own messages are untouched


def _piece(text=None, call=None, usage=None):
    delta = NS(content=text, tool_calls=[call] if call else None)
    return NS(choices=[NS(delta=delta)], usage=usage)


async def test_a_streamed_reply_is_put_back_together(kept):
    async def stream():
        yield _piece("Adding ")
        yield _piece("it.", NS(index=0, function=NS(name="task_add", arguments='{"title": ')))
        yield _piece(None, NS(index=0, function=NS(name=None, arguments='"Pay"}')))
        yield _piece(None, usage={"prompt_tokens": 9})
    seen = [part async for part in capture.kept_stream(stream(), "m", [{"role": "user", "content": "Remind me"}], None)]
    assert len(seen) == 4  # every piece handed on
    call = lines(kept)[0]
    assert call["reply"] == {"text": "Adding it.", "tool_calls": [{"name": "task_add", "arguments": '{"title": "Pay"}'}]}
    assert call["usage"] == {"prompt_tokens": 9}


async def test_the_agents_calls_are_kept_only_when_asked(isolated_settings, monkeypatch, tmp_path):
    from google.adk.models.lite_llm import LiteLLMClient

    from odie.agent.model import SavingClient
    reply = NS(choices=[NS(message=NS(content="Hi.", tool_calls=None))], usage=None)

    async def fake_send(self, model, messages, tools, **kwargs):
        return reply
    monkeypatch.setattr(LiteLLMClient, "acompletion", fake_send)
    messages = [{"role": "user", "content": "hello"}]
    assert await SavingClient().acompletion("m", messages, None) is reply
    assert not (tmp_path / "training").exists()  # off: nothing kept
    capturing(monkeypatch)
    assert await SavingClient().acompletion("m", messages, None) is reply
    assert lines(tmp_path / "training")[0]["reply"]["text"] == "Hi."
    capture.forget_all()
    assert not (tmp_path / "training").exists()


async def test_litellms_own_streamed_pieces(kept):
    from litellm.types.utils import (
        ChatCompletionDeltaToolCall,
        Delta,
        Function,
        ModelResponseStream,
        StreamingChoices,
    )

    def piece(**delta):
        return ModelResponseStream(choices=[StreamingChoices(delta=Delta(**delta))])

    async def stream():
        yield piece(content="On it.")
        yield piece(tool_calls=[ChatCompletionDeltaToolCall(index=0, id="c1", type="function",
                                                            function=Function(name="task_add", arguments='{"title":'))])
        yield piece(tool_calls=[ChatCompletionDeltaToolCall(index=0, function=Function(arguments='"Pay"}'))])
    _ = [part async for part in capture.kept_stream(stream(), "m", [{"role": "user", "content": "x"}], None)]
    assert lines(kept)[0]["reply"] == {"text": "On it.", "tool_calls": [{"name": "task_add", "arguments": '{"title":"Pay"}'}]}
