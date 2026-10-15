"""A connected app's big answer (Zapier's Gmail search sends whole emails, well over 1 MB in one event) arrives instead
of failing as "SSE stream ended without a response", and is cut to a size the model can use, with a note saying so."""
from types import SimpleNamespace

import httpx2
import pytest

from odie.agent import callbacks
from odie.plugins import mcp


async def test_an_event_over_a_megabyte_still_arrives():
    from mcp.client import streamable_http
    big = "x" * (3 * 1024 * 1024)
    body = f'event: message\ndata: {{"big": "{big}"}}\n\n'.encode()
    response = httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body,
                               request=httpx2.Request("POST", "https://mcp.example.com/mcp"))
    events = [sse async for sse in streamable_http.EventSource(response)]
    assert len(events) == 1 and len(events[0].data) > 3 * 1024 * 1024


@pytest.fixture
def plugin(isolated_settings, tmp_path, monkeypatch):
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    monkeypatch.setitem(mcp.TOOL_APP, "execute_zapier_read_action", "Zapier")
    return callbacks.OdiePlugin(s)


async def test_a_huge_app_result_is_cut_with_a_note(plugin):
    result = {"content": [{"type": "text", "text": "e" * 500_000}], "isError": False}
    tool = SimpleNamespace(name="execute_zapier_read_action")
    out = await plugin.after_tool_callback(tool=tool, tool_args={}, tool_context=SimpleNamespace(), result=result)
    text = out["content"][0]["text"]
    assert len(text) < callbacks.APP_RESULT_LIMIT + 400 and "500,000 characters" in text and "narrower" in text


async def test_a_small_app_result_is_untouched(plugin):
    result = {"content": [{"type": "text", "text": "three emails"}], "isError": False}
    tool = SimpleNamespace(name="execute_zapier_read_action")
    out = await plugin.after_tool_callback(tool=tool, tool_args={}, tool_context=SimpleNamespace(), result=result)
    assert (out or result)["content"][0]["text"] == "three emails"


async def test_a_huge_json_result_keeps_every_item_and_shortens_long_fields(plugin):
    import json
    emails = [{"subject": f"Invoice {i}", "from": "billing@example.com", "date": "2026-10-07",
               "body_html": "<p>" + "h" * 200_000 + "</p>", "attachment": "QUJD" * 300_000,
               "raw": {f"header_{n}": "v" * 90 for n in range(400)}} for i in range(30)]
    result = {"content": [{"type": "text", "text": json.dumps({"results": emails})}], "isError": False}
    tool = SimpleNamespace(name="execute_zapier_read_action")
    out = await plugin.after_tool_callback(tool=tool, tool_args={}, tool_context=SimpleNamespace(), result=result)
    text = out["content"][0]["text"]
    assert len(text) < callbacks.APP_RESULT_LIMIT + 400
    assert all(f"Invoice {i}" in text for i in range(25)) and "billing@example.com" in text  # the emails, their headers kept
    assert "more characters" in text and "[raw copy left out]" in text and "5 more items" in text
