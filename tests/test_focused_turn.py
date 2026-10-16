"""runner.focused_turn: one model turn with only the tools and the instruction it is given.

Run through the real OdieRunner and ADK with a stand-in model (an ADK BaseLlm that plays a script and records the
request ADK hands it). The point: no Odie prompt, no memory, no chat history, no Odie tools reach this model."""
from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie.store.db import Store

INSTRUCTION = "You write one page. Call save_note once with the page, then say done."


class Scripted(BaseLlm):
    """Calls save_note once, then replies "done". Records every request it receives."""
    seen: ClassVar[list] = []
    stall: ClassVar[bool] = False

    async def generate_content_async(self, llm_request, stream: bool = False):
        Scripted.seen.append(llm_request)
        if Scripted.stall:
            await asyncio.sleep(30)
        contents = llm_request.contents or []
        answered = any(p.function_response for c in contents for p in c.parts or [])
        if answered:
            part = types.Part(text="done")
        else:
            part = types.Part(function_call=types.FunctionCall(id="call-1", name="save_note", args={"text": "hello"}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


async def _runner(tmp_path, monkeypatch):
    from odie.app import runner as runner_mod
    Scripted.seen = []
    Scripted.stall = False
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking: Scripted(model="scripted"))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    r = runner_mod.OdieRunner(store)
    await r.load_plugins()
    return r


async def test_the_model_gets_only_the_given_tool_and_instruction(isolated_settings, tmp_path, monkeypatch):
    saved: list[str] = []

    def save_note(text: str) -> dict:
        """Save the note."""
        saved.append(text)
        return {"saved": True}

    r = await _runner(tmp_path, monkeypatch)
    reply = await r.focused_turn("Write the page about tides.", INSTRUCTION, [save_note])
    await r.close()

    assert reply == "done"
    assert saved == ["hello"]  # the tool ran
    first = Scripted.seen[0]
    names = [f.name for t in first.config.tools for f in t.function_declarations]
    assert names == ["save_note"]  # no Odie tool, no other tool
    system = str(first.config.system_instruction)
    # The given instruction is the whole of what Odie supplies. ADK adds one line of its own after it, naming the agent;
    # that is the only extra text. Nothing of Odie's appears: not the background brief, not the chat prompt.
    from odie.app.runner import BACKGROUND_INSTRUCTION
    adk_line = 'You are an agent. Your internal name is "odie_writer".'
    assert system == f"{INSTRUCTION}\n\n{adk_line}"
    assert BACKGROUND_INSTRUCTION not in system
    assert "You are Odie" not in system
    assert first.contents[0].parts[0].text.endswith("Write the page about tides.")  # no memory, no history before it
    assert len(first.contents) == 1


async def test_a_turn_that_runs_too_long_raises_timeout(isolated_settings, tmp_path, monkeypatch):
    r = await _runner(tmp_path, monkeypatch)
    Scripted.stall = True
    with pytest.raises(asyncio.TimeoutError):
        await r.focused_turn("Write the page.", INSTRUCTION, [], timeout=0.2)
    await r.close()


async def test_a_tool_that_raises_comes_back_to_the_model_as_its_result(isolated_settings, tmp_path, monkeypatch):
    """A tool's exception must not abort the turn: the model sees it as the tool's result and can try again."""
    def save_note(text: str) -> dict:
        """Save the note."""
        raise ValueError("boom")

    r = await _runner(tmp_path, monkeypatch)
    reply = await r.focused_turn("Write the page about tides.", INSTRUCTION, [save_note])
    await r.close()

    assert reply == "done"  # the model got its turn after the failure and finished
    second = Scripted.seen[1]
    results = [p.function_response.response for c in second.contents for p in c.parts or [] if p.function_response]
    assert len(results) == 1
    assert "boom" in results[0]["error"]


async def test_braces_in_the_instruction_reach_the_model_as_written(isolated_settings, tmp_path, monkeypatch):
    """ADK reads {name} in a plain-text instruction as a session-state value and fails when there is none; a video
    page's LaTeX ("\\frac{a}{b}") has exactly that shape. The instruction must reach the model untouched."""
    def save_note(text: str) -> dict:
        """Save the note."""
        return {"saved": True}

    braced = INSTRUCTION + ' Formulas: s.tex("f", "\\\\frac{a}{b}"); the camera is {scene, camera}.'
    r = await _runner(tmp_path, monkeypatch)
    reply = await r.focused_turn("Write the page about tides.", braced, [save_note])
    await r.close()

    assert reply == "done"
    assert str(Scripted.seen[0].config.system_instruction).startswith(braced)


async def test_a_follow_up_is_sent_once_more_in_the_same_session(isolated_settings, tmp_path, monkeypatch):
    """After the turn, follow_up is asked once; its text goes to the model as one more message in the same session,
    so the model sees the first prompt, its own tool call and the follow-up together."""
    asked: list[int] = []

    def save_note(text: str) -> dict:
        """Save the note."""
        return {"saved": True}

    def follow_up() -> str | None:
        asked.append(1)
        return "You stopped early. Finish now."

    r = await _runner(tmp_path, monkeypatch)
    reply = await r.focused_turn("Write the page about tides.", INSTRUCTION, [save_note], follow_up=follow_up)
    await r.close()

    assert asked == [1]  # asked once, not again after the follow-up's own turn
    assert reply == "done\ndone"
    assert len(Scripted.seen) == 3  # the tool call, "done", then "done" again after the follow-up
    last = Scripted.seen[2]
    texts = [p.text for c in last.contents for p in c.parts or [] if p.text]
    assert texts[0].endswith("Write the page about tides.")  # the same session: the first prompt is still there
    assert texts[-1] == "You stopped early. Finish now."


async def test_a_follow_up_with_nothing_to_say_sends_nothing(isolated_settings, tmp_path, monkeypatch):
    def save_note(text: str) -> dict:
        """Save the note."""
        return {"saved": True}

    r = await _runner(tmp_path, monkeypatch)
    reply = await r.focused_turn("Write the page about tides.", INSTRUCTION, [save_note], follow_up=lambda: None)
    await r.close()

    assert reply == "done"
    assert len(Scripted.seen) == 2
