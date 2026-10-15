"""A live check of one model path (2026-10-08): the conversation tests/test_model_contract.py plays against fake servers,
played against the real provider. A tool call, the answer from its result, then a second question with the first turn
sent exactly as before (odie.agent.compaction), streaming as chat does; a skill loaded mid-turn (its tool declared from
the start: the tool list never changes); then one turn as background checks run it. Prints what passed and the cached
share, and that every request carried the effort word (low, or medium with --thinking, the chat's "Think harder"
toggle); for Claude also that it was asked to drop a stale thought itself rather than refuse the request.
Uses the keys in Odie's .env and a throwaway store, never Odie's own data. A few tiny requests.

    scripts/model_check.sh anthropic/claude-sonnet-5-5 [--thinking]
    scripts/model_check.sh ollama/glm-5.3-flash:cloud"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

PADDING = " Keep replies short and concrete." * 300  # a prompt long enough for any provider to cache (about 2,400 tokens)
TIME_QUESTION = ("What time is it in Pune? Use the tool. Then work it out carefully: a train leaving now covers 437 km "
                 "at 73 km/h with two 17-minute stops. When does it arrive?")
SKILL_QUESTION = ("This needs care, so think before each step. I need the time in Kathmandu (UTC+5:45), New York (UTC-4) "
                  "and Tokyo (UTC+9), and the minutes until midnight in each. Load the world-clock skill, then use its "
                  "tool.")  # thinking before the skill loads and after: Claude refuses a kept thought if the tools changed


def now() -> str:
    """The current time in Pune."""
    return "18:52"


def utc_now() -> str:
    """The current time in UTC."""
    return "13:22 UTC"


def _clock_skill():
    """A skill with a tool (utc_now), as Odie's own skills have: the tool is declared from the first request on, and
    loading the skill adds only its instructions (odie.skills)."""
    from google.adk.skills.models import Frontmatter, Skill
    from google.adk.tools import FunctionTool

    from odie.skills import build_skill_toolset
    fm = Frontmatter(name="world-clock", description="The time in other time zones.", metadata={"adk_additional_tools": ["utc_now"]})
    skill = Skill(frontmatter=fm, instructions="Use utc_now for the time in UTC.")
    return build_skill_toolset(entries=[], extra_skills=[skill], extra_tools=[FunctionTool(utc_now)])


# The tool's time, or the arrival worked out from it (18:52 + 5 h 59 min + 34 min): either shows the result was used.
TIME_WORDS = ("18:52", "6:52", "1:25", "01:25", "1:26", "01:26")


async def run(provider: str, model: str, thinking: bool = False) -> list[tuple[str, bool, str]]:
    """[(check, passed, detail)]."""
    from google.adk.agents import LlmAgent
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.apps import App
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools import FunctionTool
    from google.genai import types

    from odie.agent import model as model_mod
    from odie.agent.callbacks import OdiePlugin
    from odie.agent.model import model_for
    from odie.agent.usage import CACHE, last_usage
    from odie.models import Selection, all_providers
    from odie.sampling import CHAT_TOP_P, CHECK_TEMPERATURE
    from odie.store.db import Store

    store = Store(Path(tempfile.mkdtemp(prefix="odie-model-check-")) / "check.db")
    store.init_schema()
    p = next((x for x in all_providers(store) if x.id == provider), None)
    if p is None:
        return [("provider", False, f"no provider {provider!r} here (is its key in Odie's .env?)")]
    out: list[tuple[str, bool, str]] = []
    sent: list[dict] = []  # every request as litellm got it (the saver on ADK's seam, odie.agent.model.SavingClient)
    counts = {"thoughts": 0}  # thought parts in the replies
    saving = model_mod.save_request

    def keep(kwargs: dict, folder, keep: int = 10) -> None:
        sent.append(kwargs)
        saving(kwargs, folder, keep)
    model_mod.save_request = keep

    async def turns(questions, streaming: bool, tools) -> tuple[list[str], list[str], list[str]]:
        """Each question as one turn. Returns what the model said, the tools it called, and the tools that answered
        without an error."""
        llm = model_for(Selection(p, model, "chat"), thinking)
        agent = LlmAgent(name="odie", model=llm, tools=tools,
                         instruction="You are Odie. For the time, always call the now tool." + PADDING,
                         generate_content_config=types.GenerateContentConfig(temperature=CHECK_TEMPERATURE, top_p=CHAT_TOP_P))
        sessions = InMemorySessionService()
        runner = Runner(app=App(name="odie_check", root_agent=agent, plugins=[OdiePlugin(store)], context_cache_config=CACHE),
                        session_service=sessions)
        sess = await sessions.create_session(app_name="odie_check", user_id="u")
        said, calls, answered = [], [], []
        try:
            for q in questions:
                async for ev in runner.run_async(user_id="u", session_id=sess.id,
                                                 run_config=RunConfig(streaming_mode=StreamingMode.SSE if streaming else StreamingMode.NONE),
                                                 new_message=types.Content(role="user", parts=[types.Part(text=q)])):
                    if ev.partial or not ev.content:
                        continue
                    for part in ev.content.parts or []:
                        if part.thought:
                            counts["thoughts"] += 1
                        elif part.function_call:
                            calls.append(part.function_call.name)
                        elif part.function_response and "error" not in (part.function_response.response or {}):
                            answered.append(part.function_response.name)
                        elif part.text:
                            said.append(part.text)
        finally:
            await runner.close()
        return said, calls, answered

    try:
        said, calls, _ = await turns([TIME_QUESTION, "And what time will it be in two hours?"], True, [FunctionTool(now)])
        out.append(("tool call (chat, streaming)", "now" in calls, f"calls: {calls or 'none'}"))
        out.append(("answer from the tool's result", any(w in s for s in said for w in TIME_WORDS), (said[0] if said else "no reply")[:80]))
        out.append(("second turn, the first sent as before", len(said) >= 2, (said[-1] if said else "no reply")[:80]))
        u = last_usage(store) or {}
        share = f"{u.get('cached', 0)} of {u.get('input', 0)} input tokens from cache"
        out.append(("prompt cache", bool(u.get("cached")), share))
        said, calls, answered = await turns([SKILL_QUESTION], True, [FunctionTool(now), _clock_skill()])
        out.append(("a skill loaded mid-turn, then its tool", "utc_now" in answered and bool(said),
                    f"calls: {calls or 'none'}; " + (said[-1] if said else "no reply")[:60]))
        said, calls, _ = await turns(["What time is it? Use the tool, then answer in five words."], False, [FunctionTool(now)])
        out.append(("one turn as background checks run it", bool(said) and "now" in calls, (said[-1] if said else "no reply")[:80]))
    except Exception as e:  # noqa: BLE001 (report it as a failed check, with what the provider said)
        out.append(("conversation", False, f"{type(e).__name__}: {str(e)[:300]}"))
    finally:
        model_mod.save_request = saving
    out += _wire_checks(provider, thinking, sent, counts["thoughts"])
    return out


def _wire_checks(provider: str, thinking: bool, sent: list[dict], thoughts: int) -> list[tuple[str, bool, str]]:
    """What went to litellm: the effort word on every request (low, or medium with --thinking), and for Claude the
    binding that makes it drop a stale thought itself (a refused thought would have failed the conversation above).
      8 requests all carrying "low", 3 thought parts       -> ("the effort word on every request", True, "low in 8 of 8 requests; 3 thought(s) in the replies")
      Claude, every request with the block_binding setting -> ("Claude drops a stale thought itself", True, "block_binding on 8 of 8 requests")"""
    from odie.agent.model import CLAUDE_THINKING, effort_for
    expected = effort_for(thinking)
    with_word = sum(1 for r in sent if r.get("reasoning_effort") == expected)
    checks = [("the effort word on every request", bool(sent) and with_word == len(sent),
               f"{expected} in {with_word} of {len(sent)} requests; {thoughts} thought(s) in the replies")]
    if provider == "anthropic":
        bound = sum(1 for r in sent if (r.get("thinking") or {}).get("block_binding") == CLAUDE_THINKING["block_binding"])
        checks.append(("Claude drops a stale thought itself", bool(sent) and bound == len(sent), f"block_binding on {bound} of {len(sent)} requests"))
    return checks


def main(argv: list[str]) -> int:
    thinking = "--thinking" in argv
    args = [a for a in argv if a != "--thinking"]
    if len(args) != 1 or "/" not in args[0]:
        print("usage: scripts/model_check.sh <provider>/<model> [--thinking]   e.g. anthropic/claude-sonnet-5-5, ollama/glm-5.3-flash:cloud")
        return 2
    provider, model = args[0].split("/", 1)
    print(f"{provider}/{model}, Think harder {'on' if thinking else 'off'}")
    results = asyncio.run(run(provider, model, thinking))
    for name, ok, detail in results:
        print(f"{'✓' if ok else '✗'} {name}: {detail}")
    failed = [n for n, ok, _ in results if not ok and n != "prompt cache"]  # a provider without caching still works
    print("All good." if not failed else f"{len(failed)} check(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
