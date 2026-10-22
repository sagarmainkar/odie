"""Calling a connected app's tool from code, over stdio here (HTTP goes through the same session code)."""
import json
import sys
from pathlib import Path

import pytest

from odie.watch.calls import CallError, call_tool, list_tools

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_mail.py"


def spec_for(mode, tmp_path, mail=(), events=(), **extra):
    """A fake mail server over stdio. extra: more of its data, e.g. bodies={"m1": "…"} for gmail_read, threads={…}."""
    data = tmp_path / "mail.json"
    data.write_text(json.dumps({"mail": list(mail), "events": list(events), **extra}))
    return {"command": sys.executable, "args": [str(FIXTURE), mode], "env": {"MAIL_DATA": str(data), "MAIL_LOG": str(tmp_path / "calls.log")}}


async def test_list_and_call_a_tool(tmp_path):
    spec = spec_for("plain", tmp_path, mail=[{"id": "m1", "subject": "Hi"}])
    names = [t["name"] for t in await list_tools(spec)]
    assert {"search_emails", "list_events", "send_email"} <= set(names)
    out = await call_tool(spec, "search_emails", {"query": "after:1"})
    assert out.is_error is False and json.loads(out.text)["messages"][0]["id"] == "m1"


async def test_a_server_that_wont_start_is_a_plain_reason(tmp_path):
    with pytest.raises(CallError) as e:
        await call_tool({"command": str(tmp_path / "missing"), "args": []}, "x", {}, timeout=10)
    assert str(e.value)


async def test_a_slow_call_times_out(tmp_path, monkeypatch):
    spec = spec_for("plain", tmp_path)
    with pytest.raises(CallError) as e:
        await call_tool(spec, "search_emails", {"query": "x"}, timeout=0.001)
    assert "longer than" in str(e.value)
