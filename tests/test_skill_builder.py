from pathlib import Path

import pytest

from odie import config
from odie.skills import builder
from odie.store.db import Store

GOOD = '''"""Trip helpers."""
import json

from google.adk.tools import FunctionTool

DAYS = 3


async def trip_days(city: str, days: int = DAYS) -> str:
    """Day labels for a trip to city."""
    return json.dumps([f"Day {i + 1}" for i in range(days)])


TOOLS = [FunctionTool(trip_days)]
'''

INSTR = "# Travel\n\nPlan trips. Draw the plan as a ```odie-blocks timeline with \"icon\": \"walk\" stops."


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    reloads = []

    async def reload():
        reloads.append(1)
        return {}
    builder.hooks.update(store=s, reload=reload, reserved=lambda: {"web_search": "Odie", "market_history": "the stocks skill"})
    s._reloads = reloads
    yield s
    builder.hooks.update(store=None, reload=None, reserved=None)


def _problems(code: str = GOOD, **kw) -> list[str]:
    return builder.check_code(code, reserved={"web_search": "Odie"}, **kw)


def test_good_code_passes():
    assert _problems() == []


@pytest.mark.parametrize("code, word", [
    ("def broken(:\n", "syntax"),
    ("async def a() -> str:\n    \"\"\"x\"\"\"\n    return ''\n", "TOOLS"),
    ("TOOLS = [FunctionTool(nope)]\n", "nope"),
    ("from google.adk.tools import FunctionTool\nasync def a() -> str:\n    return ''\nTOOLS = [FunctionTool(a)]\n", "docstring"),
    ("import os\nos.system('rm -rf ~')\nTOOLS = []\n", "runs when"),
    ("import surely_not_a_module_xyz\nTOOLS = []\n", "surely_not_a_module_xyz"),
    ("from google.adk.tools import FunctionTool\nasync def web_search(q: str) -> str:\n    \"\"\"x\"\"\"\n    return q\nTOOLS = [FunctionTool(web_search)]\n", "web_search"),
])
def test_code_problems(code, word):
    probs = _problems(code)
    assert probs and any(word in p for p in probs), probs


def test_blocks_and_icons_are_checked():
    assert builder.check_text("Use a ```odie-blocks tiles block", ["tiles", "timeline"]) == []
    probs = builder.check_text('a block {"type": "carousel"} with "icon": "unicorn"', ["sparkles"])
    assert any("sparkles" in p for p in probs) and any("carousel" in p for p in probs) and any("unicorn" in p for p in probs)


def test_names():
    assert builder.name_problem("travel-itinerary") is None
    assert builder.name_problem("Travel Itinerary")
    assert builder.name_problem("stocks")             # a built-in
    assert builder.name_problem("skill-builder")
    assert builder.name_problem("mcp-vault")


async def test_draft_writes_staging_and_reports(store):
    out = await builder.draft("travel-itinerary", "Plans trips day by day with places to see.", INSTR, GOOD, ["timeline", "tiles"])
    assert out.startswith("Ready to install")
    d = config.settings.config_dir / "skills-staging" / "travel-itinerary"
    text = (d / "SKILL.md").read_text()
    assert "name: travel-itinerary" in text and "blocks:" in text and "# Travel" in text
    assert (d / "tools.py").read_text() == GOOD
    assert not (config.settings.config_dir / "skills" / "travel-itinerary").exists()  # nothing installed yet


async def test_draft_with_problems_is_not_ready(store):
    out = await builder.draft("trip", "Trips.", INSTR, "def broken(:\n", [])
    assert "Not ready" in out and "syntax" in out


async def test_instructions_only_skill(store):
    out = await builder.draft("packing-list", "Packing lists for trips.", "# Packing\n\nMake a checklist.", "", [])
    assert out.startswith("Ready to install")
    assert not (config.settings.config_dir / "skills-staging" / "packing-list" / "tools.py").exists()


async def test_install_moves_trusts_and_reloads(store):
    await builder.draft("travel-itinerary", "Plans trips day by day.", INSTR, GOOD, ["timeline"])
    out = await builder.install("travel-itinerary", builder.staged_version("travel-itinerary"))
    dest = config.settings.config_dir / "skills" / "travel-itinerary"
    assert (dest / "tools.py").exists() and not (config.settings.config_dir / "skills-staging" / "travel-itinerary").exists()
    assert "travel-itinerary" in (store.get_setting("skills.trusted") or {})
    assert store._reloads == [1]
    assert "installed now" in out and "trip_days" in out


async def test_install_without_draft(store):
    assert "No draft" in await builder.install("nothing-here")


async def test_install_reports_a_load_failure(store):
    bad = GOOD.replace("return json.dumps", "raise_here = 1\n    return json.dumps")
    await builder.draft("odd", "Odd.", "# Odd", bad.replace("DAYS = 3", "DAYS = int('x')"), [])
    out = await builder.install("odd", builder.staged_version("odd"))
    assert "didn't load" in out and "ValueError" in out


def test_install_tool_needs_a_tap():
    from odie.skills.registry import _load_tools
    tools = {t.name: t for t in _load_tools(Path(builder.__file__).parent / "skill-builder", "skill-builder")}
    assert set(tools) == {"skill_guide", "read_skill", "draft_skill", "install_skill"}
    assert tools["install_skill"]._require_confirmation is True
    assert tools["draft_skill"]._require_confirmation is False


def test_approval_card_shows_the_skill(store):
    import asyncio
    asyncio.run(builder.draft("travel-itinerary", "Plans trips day by day.", INSTR, GOOD, ["timeline"]))
    from odie.app.runner import approval_from_confirmation

    class FC:
        id = "c1"
        args = {"originalFunctionCall": {"name": "install_skill", "args": {"name": "travel-itinerary",
                                                                           "version": builder.staged_version("travel-itinerary")}}}
    a = approval_from_confirmation(FC(), "i1", "s1", store)
    assert a["risk"] == "normal"
    assert a["summary"].startswith("Install skill travel-itinerary")
    assert "async def trip_days" in a["detail"]["body"] and "# Travel" in a["detail"]["body"]


async def test_install_refuses_a_draft_changed_after_the_card(store):
    out = await builder.draft("travel-itinerary", "Plans trips.", INSTR, GOOD, [])
    shown = out.split("version='")[1].split("'")[0]
    await builder.draft("travel-itinerary", "Plans trips.", INSTR, GOOD.replace("DAYS = 3", "DAYS = 4"), [])
    assert "changed" in await builder.install("travel-itinerary", shown)
    assert not (config.settings.config_dir / "skills" / "travel-itinerary").exists()


def test_the_guide_says_what_odie_has_here(store):
    # Odie built a video skill with macOS `say`, not knowing its own voice (16 Oct 2026): the guide carries it, live.
    from types import SimpleNamespace

    from odie import about
    about.hooks["runner"] = SimpleNamespace(store=store, plugins={"skills": [], "servers": []},
                                            _all_tool_names=lambda: {"speak": "Odie", "run_shell": "Odie"})
    try:
        text = builder.guide()
    finally:
        about.hooks["runner"] = None
    assert "What Odie has here" in text and "Kokoro, Heart" in text and "speak(" in text and "command -v ffmpeg" in text
    assert "What Odie has here" not in builder.guide()   # without a running Odie there's nothing live to read


def test_the_skill_builder_points_at_the_live_list():
    text = (builder.BUILTIN_DIR / "skill-builder" / "SKILL.md").read_text()
    assert "What Odie has here" in text and "never macOS `say`" in text
