from pathlib import Path

from odie.skills import build_skill_toolset
from odie.skills.registry import discover, set_enabled, trust
from odie.store.db import Store

SKILL = "---\nname: {name}\ndescription: {desc}\n---\nDo the thing.\n"
TOOLS = 'async def hello(name: str) -> str:\n    """Say hello."""\n    return f"hi {name}"\n\nTOOLS = [hello]\n'


def _skill(root: Path, name: str, desc: str = "A test skill.", tools: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL.format(name=name, desc=desc))
    if tools is not None:
        (d / "tools.py").write_text(tools)
    return d


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_builtin_skills_with_code_are_trusted_and_tools_derived(tmp_path):
    b, u = tmp_path / "b", tmp_path / "u"
    _skill(b, "greet", tools=TOOLS)
    [e] = discover(_store(tmp_path), b, u)
    assert e.status == "ok" and e.source == "builtin" and e.tools == ["hello"]
    assert e.skill.frontmatter.metadata["adk_additional_tools"] == ["hello"]


def test_user_code_is_blocked_until_trusted_and_reblocked_when_changed(tmp_path):
    s, b, u = _store(tmp_path), tmp_path / "b", tmp_path / "u"
    d = _skill(u, "greet", tools=TOOLS)
    [e] = discover(s, b, u)
    assert e.status == "blocked" and e.source == "user"
    trust(s, e)
    assert discover(s, b, u)[0].status == "ok"
    (d / "tools.py").write_text(TOOLS.replace("hi ", "hello "))
    assert discover(s, b, u)[0].status == "blocked"


def test_instruction_only_user_skill_needs_no_ok_and_overrides_builtin(tmp_path):
    s, b, u = _store(tmp_path), tmp_path / "b", tmp_path / "u"
    _skill(b, "notes", desc="Built in.")
    _skill(u, "notes", desc="Mine.")
    [e] = discover(s, b, u)
    assert e.status == "ok" and e.source == "user" and e.description == "Mine."


def test_disabled_and_broken_skills(tmp_path):
    s, b, u = _store(tmp_path), tmp_path / "b", tmp_path / "u"
    _skill(b, "good")
    _skill(b, "badcode", tools="def broken(:\n")
    (b / "nomd").mkdir(parents=True)
    (b / "nomd" / "SKILL.md").write_text("no frontmatter here")
    set_enabled(s, "good", False)
    by = {e.name: e for e in discover(s, b, u)}
    assert by["good"].status == "disabled"
    assert by["badcode"].status == "error" and "SyntaxError" in by["badcode"].reason
    assert by["nomd"].status == "error"


async def test_toolset_declares_a_trusted_user_skills_tool_from_the_start(tmp_path):
    """A user's skill's tool is declared whether or not the skill is loaded (the tool list never changes mid-chat, so
    the prompt cache holds); a skill that isn't trusted yet brings nothing."""
    from types import SimpleNamespace
    s, b, u = _store(tmp_path), tmp_path / "b", tmp_path / "u"
    _skill(u, "greet", tools=TOOLS)
    ctx = lambda active: SimpleNamespace(state={"_adk_activated_skill_odie": active} if active else {}, agent_name="odie", invocation_id="i")
    assert "hello" not in [t.name for t in await build_skill_toolset(discover(s, b, u)).get_tools(ctx([]))]  # blocked
    trust(s, discover(s, b, u)[0])
    ts = build_skill_toolset(discover(s, b, u))
    assert "hello" in [t.name for t in await ts.get_tools(ctx([]))]
    assert "hello" in [t.name for t in await ts.get_tools(ctx(["greet"]))]


def test_real_stocks_skill_is_discovered_without_a_hardcoded_import(tmp_path):
    [e] = [x for x in discover(_store(tmp_path), user_dir=tmp_path / "none") if x.name == "stocks"]
    assert e.status == "ok" and {"market_history", "quarterly_financials"} <= set(e.tools)


def test_a_disabled_skill_does_not_run_its_code(tmp_path):
    s, b, u = _store(tmp_path), tmp_path / "b", tmp_path / "u"
    marker = tmp_path / "ran.txt"
    _skill(b, "noisy", tools=f'open({str(marker)!r}, "w").write("x")\n' + TOOLS)
    set_enabled(s, "noisy", False)
    [e] = discover(s, b, u)
    assert e.status == "disabled" and not marker.exists()


def test_a_skill_calling_sys_exit_is_an_error_not_a_crash(tmp_path):
    s, b, u = _store(tmp_path), tmp_path / "b", tmp_path / "u"
    _skill(b, "quitter", tools="import sys\nsys.exit(1)\n")
    [e] = discover(s, b, u)
    assert e.status == "error" and "SystemExit" in e.reason


def test_skill_code_runs_from_its_source_never_a_bytecode_cache(tmp_path):
    # The trust hash covers tools.py; a planted __pycache__/*.pyc must not be what actually runs.
    from odie.skills.registry import _load_tools
    d = tmp_path / "s"
    d.mkdir()
    (d / "tools.py").write_text("from google.adk.tools import FunctionTool\n\nasync def hi() -> str:\n    \"\"\"Say hi.\"\"\"\n    return 'hi'\n\nTOOLS = [FunctionTool(hi)]\n")
    tools = _load_tools(d, "s")
    assert [t.name for t in tools] == ["hi"]
    assert not (d / "__pycache__").exists()
