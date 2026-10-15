"""A short live run against a real model: five chat turns through the real runner on a throwaway home.

    ODIE_LIVE=1 ODIE_LIVE_MODEL=<provider>/<model> uv run pytest tests/integration -s
    e.g. ODIE_LIVE_MODEL=ollama/glm-5.3-flash:cloud, anthropic/claude-sonnet-5-5, lmstudio/gemma-4-26b-a4b-it-qat

It reads only the one key that provider needs from ~/.odie/.env (never writes there), runs in a temporary home, and
prints each turn: seconds, tools, approval cards, tokens. It checks that the plumbing works with this model (a memory
is saved, a question about it is answered, a table is drawn, a command waits for a tap), not how good the replies are.
Skipped unless ODIE_LIVE=1, so the normal suite and CI never call a model.
"""
import importlib
import os

import pytest

import odie.app.runner as runner_mod
import odie.models as models_mod

LIVE = os.environ.get("ODIE_LIVE") == "1"
MODEL = os.environ.get("ODIE_LIVE_MODEL", "")
pytestmark = pytest.mark.skipif(not LIVE, reason="a live model run: ODIE_LIVE=1 ODIE_LIVE_MODEL=<provider>/<model>")

# The suite's own fixtures make LM Studio and Ollama look absent; this test talks to the real ones, so it keeps the
# real functions from before those fixtures run.
REAL_CONTEXT_WINDOW = runner_mod.context_window
REAL_ASK_LOCAL = models_mod.ask_local_providers

TURNS = [
    # (chat, message, what must happen)
    ("memory", "Remember that my dentist is Smile Dental.", "saves a memory"),
    ("memory", "What's my dentist called?", "answers Smile Dental"),
    ("table", "Compare three phone plans as a table: Basic ₹299 with 2 GB a day, Plus ₹399 with 3 GB a day, "
              "Max ₹599 with unlimited data.", "draws the comparison"),
    ("shell", "Run the shell command `echo hello` on this Mac.", "waits for a tap"),
    ("plain", "Thanks, that's all.", "a plain reply"),
]


def turn_passed(what: str, answer: dict) -> bool:
    """Whether a turn did its job. Examples: "saves a memory" with an update_memory call -> True;
    "answers Smile Dental" with a reply naming it -> True; "waits for a tap" with no approval card -> False;
    any turn that ended in an error -> False."""
    if answer["error"]:
        return False
    tools = [t["tool"] for t in answer["tools"]]
    reply = answer["reply"]
    if what == "saves a memory":
        return "update_memory" in tools
    if what == "answers Smile Dental":
        return "smile dental" in reply.lower()
    if what == "draws the comparison":
        drew_blocks = "```odie-" in reply
        drew_table = "|" in reply and "399" in reply
        return drew_blocks or drew_table
    if what == "waits for a tap":
        return any(e.startswith("approval card") for e in answer["events"])
    return bool(reply.strip())


@pytest.fixture
def live_home(tmp_path, monkeypatch):
    """A throwaway home for the run, with the one key the provider needs copied from ~/.odie/.env (read only)."""
    from odie import blocks_eval

    assert "/" in MODEL, "set ODIE_LIVE_MODEL=<provider>/<model>, e.g. ollama/glm-5.3-flash:cloud"
    provider, model = MODEL.split("/", 1)
    keys_from = blocks_eval.owner_env_file()  # before anything points at the throwaway home
    for name, value in blocks_eval.throwaway_env(tmp_path).items():
        monkeypatch.setenv(name, value)
    key_name = blocks_eval.key_name_for(provider)
    if key_name:
        from odie.secrets import load_secret
        key = load_secret(key_name, env_file_path=keys_from)
        assert key, f"no {key_name} in {keys_from}: {provider} can't be reached"
        monkeypatch.setenv(key_name, key)
    monkeypatch.setattr(runner_mod, "context_window", REAL_CONTEXT_WINDOW)
    monkeypatch.setattr(models_mod, "ask_local_providers", REAL_ASK_LOCAL)
    import odie.config as config
    importlib.reload(config)
    assert str(config.settings.data_dir).startswith(str(tmp_path)), "the run must stay in its throwaway home"
    yield provider, model
    monkeypatch.undo()
    importlib.reload(config)


async def test_five_turns_with_a_real_model(live_home):
    from odie import blocks_eval, config
    from odie.app.runner import OdieRunner
    from odie.store.db import Store

    provider, model = live_home
    store = Store(config.settings.db_path)
    store.init_schema()
    store.set_setting("model.chat", {"provider": provider, "model": model})
    runner = OdieRunner(store)
    runner.review_every = 10**6  # no memory review between turns: an extra model call
    await runner.load_plugins()
    counter = blocks_eval.token_counter()
    runner.runner.plugin_manager.register_plugin(counter)

    results = []
    try:
        for chat, message, what in TURNS:
            answer = await blocks_eval.ask_in(runner, message, f"smoke-{chat}", counter)
            results.append((what, answer, turn_passed(what, answer)))
    finally:
        await runner.close()
        from odie.browser import close_shared
        await close_shared()

    print(f"\nSmoke run: {provider}/{model}")
    for what, answer, passed in results:
        mark = "ok  " if passed else "FAIL"
        called = [t["tool"] for t in answer["tools"]]
        cards = [e for e in answer["events"] if e.startswith("approval card")]
        tools = ", ".join(called + cards) or "no tools"
        tokens = answer["tokens"]
        print(f"  {mark} {what:<22} {answer['seconds']:>5} s  {tools}  ({tokens['input']} in / {tokens['output']} out)")
        if answer["error"]:
            print(f"       error: {answer['error']}")
    failed = [what for what, _, passed in results if not passed]
    assert failed == [], f"{len(failed)} of {len(TURNS)} turns didn't do their job: {', '.join(failed)}"
