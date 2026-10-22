import sys
from pathlib import Path

from odie.plugins import mcp as m
from odie.plugins.mcp import is_read_only, toolset_for

TESTER = {"command": sys.executable, "args": [str(Path(__file__).parent / "fixtures" / "mcp_tester.py")]}


async def test_read_only_tools_run_freely_others_ask():
    ts = toolset_for("tester", TESTER)
    try:
        tools = {t.name: t for t in await ts.get_tools()}
        assert set(tools) == {"echo", "write_note"}
        assert is_read_only(tools["echo"]) and not is_read_only(tools["write_note"])
        assert await tools["echo"].check_require_confirmation({"text": "x"}, None) is False
        assert await tools["write_note"].check_require_confirmation({"text": "x"}, None) is True
    finally:
        await ts.close()


def test_http_spec_builds_streamable_params():
    ts = toolset_for("vault", {"url": "http://127.0.0.1:9/mcp", "headers": {"X-Profile": "odie"}})
    assert ts._connection_params.url.endswith("/mcp") and ts._connection_params.headers["X-Profile"] == "odie"


async def test_on_demand_server_becomes_a_skill_with_its_tools(isolated_settings):
    m.write_config({"tester": {**TESTER, "description": "Test tools"}})
    [e] = await m.load_servers(timeout=20)
    try:
        assert e.status == "ok" and sorted(e.tools) == ["echo", "write_note"] and not e.always_on
        assert e.skill.frontmatter.name == "mcp-tester" and e.skill.frontmatter.description == "Test tools"
        assert sorted(e.skill.frontmatter.metadata["adk_additional_tools"]) == ["echo", "write_note"]
    finally:
        await e.toolset.close()


async def test_description_falls_back_to_tool_names(isolated_settings):
    m.write_config({"tester": TESTER})
    [e] = await m.load_servers(timeout=20)
    try:
        assert "echo" in e.skill.frontmatter.description
    finally:
        await e.toolset.close()


async def test_hung_or_broken_servers_fail_fast_and_bad_json_is_an_error(isolated_settings):
    m.write_config({"hang": {"command": "sleep", "args": ["30"]}, "Bad_Name": TESTER})
    by = {e.name: e for e in await m.load_servers(timeout=2)}
    assert by["hang"].status == "failed" and by["Bad_Name"].status == "error"
    m.mcp_path().write_text("{not json")
    servers, err = m.read_config()
    assert servers == {} and err


async def test_clashing_tool_names_mark_the_second_server(isolated_settings):
    m.write_config({"a": TESTER, "b": TESTER})
    by = {e.name: e for e in await m.load_servers(timeout=20)}
    try:
        assert by["a"].status == "ok" and by["b"].status == "error" and "clash" in by["b"].reason
    finally:
        for e in by.values():
            if e.toolset:
                await e.toolset.close()


def test_masked_hides_secret_values():
    out = m.masked({"command": "x", "env": {"TOKEN": "abc"}, "headers": {"Authorization": "Bearer z"}})
    assert out["env"] == {"TOKEN": "••••"} and out["headers"] == {"Authorization": "••••"}


async def test_a_hung_server_leaves_no_process_behind(isolated_settings):
    import subprocess
    m.write_config({"hang": {"command": "sleep", "args": ["4321"]}})
    [e] = await m.load_servers(timeout=2)
    assert e.status == "failed" and "timed out" in e.reason
    left = subprocess.run(["pgrep", "-f", "sleep 4321"], capture_output=True, text=True).stdout.split()
    assert left == []


async def test_server_tools_may_not_shadow_odies_own(isolated_settings):
    m.write_config({"tester": TESTER})
    [e] = await m.load_servers(timeout=20, reserved={"echo": "Odie"})
    assert e.status == "error" and "clash" in e.reason and "Odie" in e.reason


async def test_a_cancelled_listing_kills_its_helper():
    import asyncio
    import subprocess
    task = asyncio.create_task(m.probe_tools({"command": "sleep", "args": ["9876"]}, 30))
    await asyncio.sleep(1.5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.3)
    left = subprocess.run(["pgrep", "-f", "sleep 9876|odie.plugins.probe"], capture_output=True, text=True).stdout.split()
    assert left == []


def test_a_mail_apps_skill_says_how_to_show_mail_and_others_dont():
    """Only an app with a mail listing gets the "How to show mail" paragraph; it lives in the skill, not the prompt."""
    mail = m._skill_for("gmail-calendar", "My mail", ["gmail_search", "gmail_read", "calendar_list_events"])
    vault = m._skill_for("obsidian-vault", "My notes", ["search_notes", "read_note"])
    assert "How to show mail" in mail.instructions and '"Needs you"' in mail.instructions
    assert mail.instructions.startswith("Tools from the gmail-calendar MCP server: gmail_search, gmail_read")
    assert "How to show mail" not in vault.instructions
    assert len(m.SHOW_MAIL) / 4 <= 160  # ~150 tokens; it's read only after load_skill, but keep it short


def test_a_mail_rows_tap_opens_that_mail_by_its_id():
    # A row's tap is a new chat turn: with the mail's id in it, chat reads that mail instead of searching for it.
    assert '"run":"Open the email from Asha about the lease renewal (id ' in m.SHOW_MAIL
