"""Connected apps: the Zapier and Composio presets, the check that lists a server's tools before it is saved, and the
per-server switch that lets reads run without a tap (never anything that changes something)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from google.adk.tools.mcp_tool import McpToolset

from odie.plugins import mcp, presets
from odie.plugins.mcp import asks, is_read_name, toolset_for
from odie.store.db import Store

APPS = {"command": sys.executable, "args": [str(Path(__file__).parent / "fixtures" / "mcp_apps.py")]}
ZAPIER = "https://mcp.zapier.com/api/mcp/s/ZjM4NzQ1YTMtOWQ2Yi00ZTEyLWE3ZjAtZDc5YTBkNTRhMTQ3OjhlMmE1ZWQ0/mcp"
ZAPIER2 = "https://mcp.zapier.com/api/mcp/s/QWxsIHRoZSB0aGluZ3MgYXJlIGZpbmUxMjM0NTY3OA/mcp"
COMPOSIO = "https://mcp.composio.dev/composio/server/2f1c9a3e-8b7d-4e6f-9a1b-3c5d7e9f1a2b/mcp?user_id=asha"
TOOLS = [{"name": "gmail_find_email", "read_only": False, "destructive": False},
         {"name": "gmail_send_email", "read_only": False, "destructive": False}]


@pytest.mark.parametrize("name", ["gmail_find_email", "GMAIL_FETCH_EMAILS", "list_items", "COMPOSIO_SEARCH_TOOLS",
                                  "getCalendarEvents", "search", "slack_get_message", "airtable_get_record", "shopify_get_order"])
def test_read_names(name):
    assert is_read_name(name)


@pytest.mark.parametrize("name", ["gmail_send_email", "GMAIL_SEND_EMAIL", "COMPOSIO_MULTI_EXECUTE_TOOL", "get_or_create_contact",
                                  "delete_list", "listen_and_reply", "create_item", "items", "fetchAndDelete", "search_and_replace",
                                  "get_and_clear", "list_then_purge", "fetch_and_merge", "GOOGLESHEETS_FIND_AND_REPLACE", "find_and_sync",
                                  "get_and_revoke", "list_and_rename", "search_and_snooze"])
def test_change_names_are_not_reads(name):
    assert not is_read_name(name)


def test_asks():
    assert asks({"name": "write_note", "read_only": True}, False) is True  # the server's own word frees nothing
    assert asks({"name": "list_items", "read_only": False}, False) is True  # the switch is off
    assert asks({"name": "list_items", "read_only": False}, True) is False  # the user's switch, and a name that reads
    assert asks({"name": "list_items", "read_only": True}, True) is False
    assert asks({"name": "create_item", "read_only": False}, True) is True
    assert asks({"name": "delete_thread", "read_only": True}, True) is True  # marked read-only, but its name says otherwise
    assert asks({"name": "send_mail", "read_only": True}, True) is True
    assert asks({"name": "fetch_report", "read_only": False, "destructive": True}, True) is True


def test_asks_in_smart():
    # Smart: only the ask-words in the name, or the server's destructive mark, ask. The reads_free switch no longer matters.
    assert asks({"name": "GMAIL_SEND_EMAIL"}, False, smart=True) is True
    assert asks({"name": "GMAIL_FETCH_EMAILS"}, False, smart=True) is False
    assert asks({"name": "write_note", "read_only": True}, False, smart=True) is False  # an ordinary write runs
    assert asks({"name": "delete_note"}, False, smart=True) is True
    assert asks({"name": "list_items"}, False, smart=True) is False  # runs even with the reads switch off
    assert asks({"name": "fetch_report", "destructive": True}, True, smart=True) is True  # innocent name, marked destructive
    assert asks({"name": "COMPOSIO_MULTI_EXECUTE_TOOL"}, True, smart=True) is True


def test_asks_in_careful_is_unchanged():
    assert asks({"name": "write_note"}, False, smart=False) is True
    assert asks({"name": "list_items"}, False, smart=False) is True
    assert asks({"name": "list_items"}, True, smart=False) is False
    assert asks({"name": "GMAIL_FETCH_EMAILS"}, False) is True  # smart defaults to Careful


class _Fakes:
    """What a server lists, without a server: tools with a name and the hints the toolset reads."""

    def __init__(self, *names):
        self.tools = [SimpleNamespace(name=n, raw_mcp_tool=None, _require_confirmation=None) for n in names]

    async def get_tools(self, readonly_context=None):
        return self.tools


async def test_the_toolset_reads_the_mode_on_every_listing(monkeypatch):
    fakes = _Fakes("write_note", "delete_note")
    monkeypatch.setattr(McpToolset, "get_tools", _Fakes.get_tools.__get__(fakes))
    mode = {"smart": False}
    ts = toolset_for("notes", {"command": "unused"}, smart=lambda: mode["smart"])

    def asked():
        return {t.name: t._require_confirmation for t in fakes.tools}
    await ts.get_tools()
    assert asked() == {"write_note": True, "delete_note": True}  # Careful: everything asks
    mode["smart"] = True
    await ts.get_tools()
    assert asked() == {"write_note": False, "delete_note": True}  # flipped mid-chat: the next listing sees it
    mode["smart"] = False
    await ts.get_tools()
    assert asked() == {"write_note": True, "delete_note": True}  # and back


async def test_a_listed_tool_remembers_what_careful_would_do(monkeypatch):
    fakes = _Fakes("write_note", "list_items")
    monkeypatch.setattr(McpToolset, "get_tools", _Fakes.get_tools.__get__(fakes))
    await toolset_for("notes", {"command": "unused", "readsFree": True}, smart=lambda: True).get_tools()
    write, read = fakes.tools
    assert (write._require_confirmation, write._asks_in_careful) == (False, True)  # Smart runs it; background turns still refuse
    assert (read._require_confirmation, read._asks_in_careful) == (False, False)


async def test_a_mode_reader_that_fails_means_careful(monkeypatch):
    fakes = _Fakes("write_note")
    monkeypatch.setattr(McpToolset, "get_tools", _Fakes.get_tools.__get__(fakes))

    def broken():
        raise RuntimeError("database is locked")
    tools = await toolset_for("notes", {"command": "unused"}, smart=broken).get_tools()
    assert tools is fakes.tools and tools[0]._require_confirmation is True


async def test_a_toolset_with_no_mode_is_careful(monkeypatch):
    fakes = _Fakes("write_note")
    monkeypatch.setattr(McpToolset, "get_tools", _Fakes.get_tools.__get__(fakes))
    await toolset_for("notes", {"command": "unused"}).get_tools()
    assert fakes.tools[0]._require_confirmation is True


def test_toolset_for_keeps_the_mode_reader():
    def reader():
        return True
    assert toolset_for("notes", {"command": "unused"}, smart=reader).smart is reader
    assert toolset_for("notes", {"command": "unused"}).smart is None


async def test_smart_with_a_real_server():
    ts = toolset_for("apps", {**APPS}, smart=lambda: True)
    try:
        tools = {t.name: t for t in await ts.get_tools()}
        asked = {n: await t.check_require_confirmation({}, None) for n, t in tools.items()}
        # create_item runs, list_items and get_status run (reads switch is off), fetch_report is marked destructive
        assert asked == {"list_items": False, "create_item": False, "fetch_report": True, "get_status": False}
    finally:
        await ts.close()


async def test_check_preview_follows_the_mode(client, monkeypatch):
    monkeypatch.setattr(mcp, "probe_tools", _probe())
    spec = {"spec": {"url": ZAPIER}}
    assert [t["asks"] for t in (await client.post("/api/mcp/check", json=spec)).json()["tools"]] == [True, True]
    await client.put("/api/approvals/mode", json={"mode": "smart"})
    assert [t["asks"] for t in (await client.post("/api/mcp/check", json=spec)).json()["tools"]] == [False, True]


async def test_reads_free_only_skips_reads():
    expect = {False: {"list_items": True, "create_item": True, "fetch_report": True, "get_status": True},
              True: {"list_items": False, "create_item": True, "fetch_report": True, "get_status": False}}
    for free, want in expect.items():
        ts = toolset_for("apps", {**APPS, "readsFree": free})
        try:
            tools = {t.name: t for t in await ts.get_tools()}
            assert {n: await t.check_require_confirmation({}, None) for n, t in tools.items()} == want, free
        finally:
            await ts.close()


async def test_the_probe_reports_destructive_tools():
    listed = {t["name"]: t for t in await mcp.probe_tools(APPS, 20)}
    assert listed["fetch_report"]["destructive"] is True and listed["list_items"]["destructive"] is False
    assert listed["get_status"]["read_only"] is True


def test_spec_for_presets():
    z = presets.spec_for("zapier", f" {ZAPIER} ")
    assert z == {"url": ZAPIER, "title": "Zapier", "description": z["description"]} and "Zapier" in z["description"]
    assert presets.spec_for("zapier", "https://mcp.zapier.com/api/mcp/mcp", " tok-ABC123 ")["headers"] == {"Authorization": "Bearer tok-ABC123"}
    c = presets.spec_for("composio", COMPOSIO, "ck_AbCdEf0123456789AbCd")
    assert c["headers"] == {"x-api-key": "ck_AbCdEf0123456789AbCd"} and c["title"] == "Composio"
    assert presets.spec_for("composio", "https://backend.composio.dev/v3/mcp/abc/mcp")["url"].startswith("https://backend.")
    for bad in (("zapier", "http://mcp.zapier.com/api/mcp/mcp"), ("zapier", "https://mcp.zapier.com.evil.example/x"),
                ("composio", ZAPIER), ("nope", "https://x.example"), ("zapier", ""), ("composio", "https://notcomposio.dev/x")):
        with pytest.raises(ValueError):
            presets.spec_for(*bad)
    assert presets.preset_of(COMPOSIO) == "composio" and presets.preset_of(ZAPIER) == "zapier"
    assert presets.preset_of("https://example.com/x") is None


@pytest.fixture
async def client(isolated_settings, tmp_path):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c


def _probe(seen=None):
    async def probe(spec, timeout):
        if seen is not None:
            seen.append(spec)
        if "fail" in spec.get("url", ""):
            raise RuntimeError(f"Client error '401 Unauthorized' for url '{spec['url']}'")
        return TOOLS
    return probe


async def test_presets_route(client):
    got = (await client.get("/api/mcp/presets")).json()
    assert [p["id"] for p in got] == ["zapier", "composio"] and all(p["where"] and p["key_label"] for p in got)


async def test_check_lists_tools_without_saving(client, monkeypatch):
    monkeypatch.setattr(mcp, "probe_tools", _probe())
    r = (await client.post("/api/mcp/check", json={"spec": {"url": ZAPIER}})).json()
    assert r == {"ok": True, "tools": [{"name": "gmail_find_email", "read_only": False, "asks": True},
                                       {"name": "gmail_send_email", "read_only": False, "asks": True}]}
    assert mcp.read_config()[0] == {}
    r = (await client.post("/api/mcp/check", json={"spec": {"url": ZAPIER, "readsFree": True}})).json()
    assert [t["asks"] for t in r["tools"]] == [False, True]
    for spec in ({"command": "/bin/sh", "args": ["-c", "id > /tmp/x"]}, {"command": "zsh", "args": ["-c", "id"]},
                 {"command": "python3", "args": ["-c", "import os"]}, {"command": "node", "args": ["-e", "1"]},
                 {"command": "node", "args": ["server.js"], "env": {"NODE_OPTIONS": "--require /tmp/x.js"}},
                 {"command": "env", "args": ["sh", "-c", "id > /tmp/x"]},        # the review's live bypasses (25 Oct 2026)
                 {"command": "python3", "args": ["-cimport pathlib; pathlib.Path('/tmp/x').write_text('hi')"]}):
        r = await client.post("/api/mcp/check", json={"spec": spec})
        assert r.status_code == 422, spec  # a shell, code as text or a hooked env: never run, not even to list tools
        r = await client.post("/api/mcp", json={"name": "evil", "spec": spec})
        assert r.status_code == 422 and mcp.read_config()[0] == {}, spec  # and never saved, so never respawned at boot
    bad = (await client.post("/api/mcp/check", json={"spec": {"url": ZAPIER.replace("/s/", "/s/fail")}})).json()
    assert bad["ok"] is False and "401" in bad["reason"] and ZAPIER.split("/")[-2] not in bad["reason"]


async def test_check_unmasks_an_edit(client, monkeypatch):
    seen = []
    monkeypatch.setattr(mcp, "probe_tools", _probe(seen))
    mcp.write_config({"zapier": {"url": ZAPIER}})
    shown = (await client.get("/api/mcp")).json()["servers"][0]["spec"]["url"]
    assert ZAPIER.split("/")[-2] not in shown
    assert (await client.post("/api/mcp/check", json={"name": "zapier", "spec": {"url": shown}})).json()["ok"]
    assert seen[-1]["url"] == ZAPIER
    assert (await client.post("/api/mcp/check", json={"spec": {"url": shown}})).status_code == 422  # nothing saved to restore


async def test_connect_saves_and_names_it(client, monkeypatch):
    monkeypatch.setattr(mcp, "probe_tools", _probe())
    r = (await client.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER})).json()
    assert r["ok"] and r["name"] == "zapier" and [t["name"] for t in r["tools"]] == ["gmail_find_email", "gmail_send_email"]
    await client.post("/api/mcp/zapier/reads_free", json={"on": True})
    again = (await client.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER, "key": "tok-1234567"})).json()
    assert again["name"] == "zapier" and again["replaced"] is True  # the same link again updates it in place
    saved = mcp.read_config()[0]
    assert set(saved) == {"zapier"} and saved["zapier"]["url"] == ZAPIER and saved["zapier"]["title"] == "Zapier"
    assert saved["zapier"]["readsFree"] is True and saved["zapier"]["headers"] == {"Authorization": "Bearer tok-1234567"}


async def test_connecting_the_same_app_again_replaces_it(client, monkeypatch):
    monkeypatch.setattr(mcp, "probe_tools", _probe())
    await client.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER, "key": "old-code-123"})
    await client.post("/api/mcp/zapier/reads_free", json={"on": True})
    r = (await client.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER2})).json()  # a new link: the code in it
    assert r["name"] == "zapier" and r["replaced"] is True
    saved = mcp.read_config()[0]
    assert set(saved) == {"zapier"} and saved["zapier"]["url"] == ZAPIER2 and "headers" not in saved["zapier"]  # the old code goes
    assert saved["zapier"]["readsFree"] is True  # its switches stay
    r = (await client.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER, "add": True})).json()
    assert r["name"] == "zapier-2" and r["replaced"] is False and set(mcp.read_config()[0]) == {"zapier", "zapier-2"}
    r = await client.post("/api/mcp/connect", json={"preset": "zapier", "url": "https://mcp.zapier.com/api/mcp/s/Zz9yXx8wWv7uUt6sSr5qQp4oOn3/mcp"})
    assert r.status_code == 409 and "two Zapier" in r.json()["detail"]  # two of them and a new link: which one? ask
    assert set(mcp.read_config()[0]) == {"zapier", "zapier-2"}


async def test_connect_refuses_a_failing_server_with_a_scrubbed_reason(client, monkeypatch):
    monkeypatch.setattr(mcp, "probe_tools", _probe())
    bad = "https://mcp.zapier.com/api/mcp/s/fail0ZjM4NzQ1YTMtOWQ2Yi00ZTEy/mcp"
    r = await client.post("/api/mcp/connect", json={"preset": "zapier", "url": bad})
    assert r.status_code == 422 and "401" in r.json()["detail"] and "fail0ZjM4NzQ1YTMtOWQ2Yi00ZTEy" not in r.text
    r = await client.post("/api/mcp/connect", json={"preset": "zapier", "url": "https://evil.example/x"})
    assert r.status_code == 422 and "Zapier" in r.json()["detail"]
    assert mcp.read_config()[0] == {}


async def test_reads_free_route(client):
    mcp.write_config({"zapier": {"url": ZAPIER}})
    assert (await client.post("/api/mcp/zapier/reads_free", json={"on": True})).status_code == 200
    assert mcp.read_config()[0]["zapier"]["readsFree"] is True
    assert (await client.get("/api/mcp")).json()["servers"][0]["readsFree"] is True
    assert (await client.post("/api/mcp/nope/reads_free", json={"on": True})).status_code == 404


async def test_a_preset_can_be_checked_without_saving(client, monkeypatch):
    monkeypatch.setattr(mcp, "probe_tools", _probe())
    r = (await client.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER, "check_only": True})).json()
    assert r["ok"] and r["name"] is None and [t["asks"] for t in r["tools"]] == [True, True]
    assert mcp.read_config()[0] == {}


def test_a_link_with_its_own_token_ignores_the_code_box():
    from odie.plugins import presets
    spec = presets.spec_for("zapier", "https://mcp.zapier.com/api/v1/connect?token=QUJDREVGR0hJSktMTU5PUA==", "an-old-code-123")
    assert "headers" not in spec  # the code in the link is the one Zapier checks; a second one made it refuse
    assert presets.spec_for("zapier", "https://mcp.zapier.com/api/v1/connect", "code-123")["headers"] == {"Authorization": "Bearer code-123"}


def test_zapiers_stale_link_reason_says_what_to_do():
    from odie.plugins import presets
    said = presets.plain_reason("zapier", "ConnectionError: Failed to create MCP session: Server 11111111-2222-4333-8444-555555555555 not found or invalid secret")
    assert "doesn't accept this link" in said and "Connect" in said and "11111111" not in said
    said = presets.plain_reason("zapier", "MCPError: Invalid OAuth token - please re-authenticate")
    assert "code" in said and "doesn't accept" in said
    assert presets.plain_reason("zapier", "ConnectTimeout") == "ConnectTimeout"  # anything else as it was


def test_name_words():
    assert mcp.name_words("GMAIL_SEND_EMAIL") == {"gmail", "send", "email"}
    assert mcp.name_words("shareLink") == {"share", "link"}
