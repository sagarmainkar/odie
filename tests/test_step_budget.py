"""Near the end of a turn's steps the model is told to answer with what it has, and its last step has no tools, so a turn
ends with an answer instead of "I stopped after 40 steps" (a loop on a bot-check page threw away what was found)."""
from types import SimpleNamespace

import pytest

from odie.agent import callbacks
from odie.app.runner import MAX_LLM_CALLS


@pytest.fixture
def plugin(isolated_settings, tmp_path):
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return callbacks.OdiePlugin(s)


def request():
    return SimpleNamespace(contents=[], config=SimpleNamespace(tools=["web_search"], system_instruction="Be Odie."), tools_dict={"web_search": object()})


async def test_the_last_steps_answer_with_what_there_is(plugin):
    ctx = SimpleNamespace(invocation_id="inv-1")
    seen = []
    for _ in range(MAX_LLM_CALLS):
        r = request()
        await plugin.before_model_callback(callback_context=ctx, llm_request=r)
        seen.append(r)
    assert "answer now" not in seen[MAX_LLM_CALLS - 9].config.system_instruction
    assert "answer now" in seen[MAX_LLM_CALLS - 6].config.system_instruction and seen[MAX_LLM_CALLS - 6].config.tools
    assert not seen[-1].config.tools and not seen[-1].tools_dict  # the last step can only write the answer
    fresh = request()
    await plugin.before_model_callback(callback_context=SimpleNamespace(invocation_id="inv-2"), llm_request=fresh)
    assert fresh.config.tools and "answer now" not in fresh.config.system_instruction  # each turn counts its own
