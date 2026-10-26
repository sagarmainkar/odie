"""A form's answer is an ordinary user message: a line for people, then an ```odie-form-answer fence for the model.
Anywhere the server uses the user's words to look things up (notes, add-ons, memory) or shows them as a title or a
search snippet, the fence is noise and is left out (odie.blocks.answers)."""
import importlib
import time

import pytest

from odie import config, threads
from odie.app.runner import OdieRunner
from odie.blocks.answers import without_form_answers
from odie.store.db import Store
from tests.test_threads import _say

LINE = "Where: Hills · Pace: Easy · Budget: 12 k"
ANSWER = LINE + '\n\n```odie-form-answer\n{"form": "trip", "values": {"where": "Hills", "pace": "Easy", "spend": 12}}\n```'


def test_the_answer_fence_is_left_out():
    assert without_form_answers(ANSWER) == LINE
    assert without_form_answers("Plain words.") == "Plain words."
    assert without_form_answers("Before\n```odie-form-answer\n{}\n```\nAfter") == "Before\nAfter"
    assert without_form_answers("A table:\n```odie-blocks\n[]\n```") == "A table:\n```odie-blocks\n[]\n```"  # other fences stay


@pytest.fixture
async def runner(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    yield r
    await r.close()


async def test_a_thread_titled_by_a_form_answer_shows_its_line(runner):
    t = time.time() - 86400
    await _say(runner, "chat-2026-10-20", "user", ANSWER, t)
    await _say(runner, "chat-2026-10-20", "odie", "Booked the hills plan.", t + 5)
    [row] = threads.list_threads(runner.store)
    assert row["title"].startswith("Where: Hills") and "odie-form-answer" not in row["title"]
    assert threads.list_threads(runner.store, q="spend") == []  # a field id only the fence carries finds nothing
    assert "odie-form-answer" not in threads.list_threads(runner.store, q="pace")[0]["snippet"]


async def test_a_turns_lookups_use_the_line_not_the_fence(runner, monkeypatch):
    from odie.agent import prefetch
    from odie.app import runner as runner_mod
    from tests.test_append_only import SESSION, Scripted
    monkeypatch.setenv("ODIE_PREFETCH", "1")
    importlib.reload(config)
    looked_up: dict[str, str] = {}

    async def gather(current, previous, vault_fn=None):
        looked_up["notes and add-ons"] = current
        return ""

    def memory(text):
        looked_up["memory"] = text
        return ""
    monkeypatch.setattr(prefetch, "gather", gather)
    monkeypatch.setattr(runner, "prefetch", memory)
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking: Scripted(model="scripted"))
    Scripted.script = {ANSWER: ["Thanks."]}
    events = [e async for e in runner.chat(ANSWER, session_id=SESSION)]
    assert not [e for e in events if e["type"] == "error"], events
    assert looked_up == {"notes and add-ons": LINE, "memory": LINE}
    assert runner._recent[SESSION][0] == LINE  # the question the next turn's lookups remember
