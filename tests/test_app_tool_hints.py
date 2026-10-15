"""A model that calls an app's tool before loading its skill, or loads a skill by a wrong name (mcp-zapier for
mcp-zapier-2), is told the right one, instead of a bare "no tool with that name" or "skill not found" that it gives up
on (it then told the user Zapier had dropped off)."""
from types import SimpleNamespace

import pytest

from odie.agent import callbacks
from odie.plugins import mcp


@pytest.fixture
def plugin(isolated_settings, tmp_path, monkeypatch):
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    monkeypatch.setattr(mcp, "TOOL_APP", {})
    monkeypatch.setattr(mcp, "TOOL_SKILL", {})
    mcp._set_tool_apps([("Zapier", "ok", ["inspect_zapier_actions", "execute_zapier_read_action"], "mcp-zapier-2"),
                        ("Notes", "error", ["read_note"], "mcp-notes")])
    return callbacks.OdiePlugin(s)


def test_each_working_apps_tools_know_their_skill(plugin):
    assert mcp.TOOL_SKILL == {"inspect_zapier_actions": "mcp-zapier-2", "execute_zapier_read_action": "mcp-zapier-2"}
    assert mcp.TOOL_APP["inspect_zapier_actions"] == "Zapier"


async def test_an_app_tool_called_before_its_skill_says_which_skill(plugin):
    tool = SimpleNamespace(name="inspect_zapier_actions")
    out = await plugin.on_tool_error_callback(tool=tool, tool_args={}, tool_context=SimpleNamespace(),
                                              error=ValueError("Tool 'inspect_zapier_actions' not found."))
    assert out and "load_skill" in out["error"] and "mcp-zapier-2" in out["error"] and "Zapier" in out["error"]


async def test_other_tool_errors_are_left_alone(plugin):
    tool = SimpleNamespace(name="web_search")
    assert await plugin.on_tool_error_callback(tool=tool, tool_args={}, tool_context=SimpleNamespace(), error=ValueError("x")) is None


async def test_a_wrong_skill_name_gets_the_close_ones(plugin):
    tool = SimpleNamespace(name="load_skill")
    result = {"error": "Skill 'mcp-zapier' not found.", "error_code": "SKILL_NOT_FOUND"}
    out = await plugin.after_tool_callback(tool=tool, tool_args={"skill_name": "mcp-zapier"}, tool_context=SimpleNamespace(), result=result)
    assert out and "mcp-zapier-2" in out["error"] and out["error_code"] == "SKILL_NOT_FOUND"
