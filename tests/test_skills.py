from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest

from odie.skills import build_skill_toolset


async def _tools(ts, active: list[str]):
    ctx = SimpleNamespace(state={"_adk_activated_skill_odie": active} if active else {}, agent_name="odie", invocation_id="i1")
    return sorted(t.name for t in await ts.get_tools(ctx))


async def test_every_skills_tools_are_declared_before_it_loads(isolated_settings):
    """The tool list never changes mid-chat (2026-10-12: a skill's tools joining mid-turn and leaving at the next one
    made GLM re-read the whole prompt, 0% reusable, twice): stocks' tools are there before and after it loads."""
    ts = build_skill_toolset()
    before = await _tools(ts, [])
    assert "load_skill" in before and {"market_history", "quarterly_financials", "track", "list_trackers"} <= set(before)
    assert "run_skill_script" not in before
    assert "unload_skill" not in before  # glm-5.3 unloaded a skill before writing its answer
    assert await _tools(ts, ["stocks"]) == before


async def test_catalog_with_the_stocks_description_is_in_the_instructions(isolated_settings):
    ts = build_skill_toolset()
    req = LlmRequest()
    await ts.process_llm_request(tool_context=SimpleNamespace(state={}, agent_name="odie", invocation_id="i1"), llm_request=req)
    assert "last 4 quarters of results" in str(req.config.system_instruction)


def test_skill_tools_come_through_the_skill_toolset(isolated_settings, tmp_path):
    """The agent's own list has no market tool: the skill toolset declares it (with its skill's catalog entry)."""
    from odie.agent.agent import build_agent
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    tools = build_agent(s).tools
    names = [getattr(t, "name", type(t).__name__) for t in tools]
    assert "market_history" not in names and any(type(t).__name__ == "FixedToolsSkillToolset" for t in tools)


async def test_a_loaded_skill_stays_and_its_instructions_stay_in_the_history(isolated_settings):
    """A skill loaded in one turn is never released: ADK doesn't rewrite its instructions out of the next turn's
    history (that would change what the model already read, and break the prompt cache), and the tools are the same
    in every turn. Odie's plugin notes that the instructions stay (callbacks._skill_stays)."""
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    ts = build_skill_toolset()
    state: dict = {}

    def ctx(inv):
        return SimpleNamespace(state=state, agent_name="odie", invocation_id=inv)

    async def names(inv):
        return {t.name for t in await ts.get_tools(ctx(inv))}
    load = next(t for t in await ts.get_tools(ctx("turn-1")) if t.name == "load_skill")
    loaded = await load.run_async(args={"skill_name": "stocks"}, tool_context=ctx("turn-1"))
    assert "lifecycle_notice" not in loaded and loaded["instructions"]
    assert await names("turn-1") == await names("turn-2")
    response = types.Part(function_response=types.FunctionResponse(name="load_skill", response=loaded))
    req = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="Analyse TCS")]),
                               types.Content(role="user", parts=[response]),
                               types.Content(role="user", parts=[types.Part(text="and Infosys?")])])
    await ts.process_llm_request(tool_context=ctx("turn-2"), llm_request=req)
    assert req.contents[1].parts[0].function_response.response == loaded  # not pruned in the next turn

