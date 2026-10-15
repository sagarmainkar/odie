import json
from types import SimpleNamespace

import httpx
import pytest

from odie.app.main import create_app
from odie.app.runner import approval_from_confirmation
from odie.store.db import Store


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def _fc(tool, args):
    return SimpleNamespace(id="r", name="adk_request_confirmation", args={"originalFunctionCall": {"id": "c", "name": tool, "args": args}, "toolConfirmation": {}})


def test_provenance_is_per_turn_not_time_based(tmp_path):
    s = _store(tmp_path)
    s.audit("user", "message", result_summary="trash amazon mail", session_id="c")
    s.log_mail_seen("c", "i1", "Amazon <m@amazon.in>", "Your order", via="gmail_read")
    s.audit("user", "message", result_summary="run lms ps", session_id="c")   # next turn, no mail
    a = approval_from_confirmation(_fc("run_shell", {"command": "lms ps"}), "i2", "c", s)
    assert a["risk"] == "mail_earlier" and a["provenance"][0]["turn"] == "previous"
    s.audit("user", "message", result_summary="and again", session_id="c")   # two turns later: nothing
    b = approval_from_confirmation(_fc("run_shell", {"command": "lms ps"}), "i3", "c", s)
    assert b["risk"] == "normal" and b["provenance"] == []
    s.log_mail_seen("c", "i3", "IT <h@acme-support.example>", "Quota", via="gmail_read")
    c = approval_from_confirmation(_fc("gmail_trash", {"message_id": "m"}), "i3", "c", s)
    assert c["risk"] == "from_email" and c["provenance"][0]["turn"] == "current"


def test_shell_path_includes_user_bins():
    from odie.agent.tools.shell import SHELL_PATH
    assert "/.lmstudio/bin" in SHELL_PATH and "/.local/bin" in SHELL_PATH and "/opt/homebrew/bin" in SHELL_PATH


class FakeRunner:
    async def chat(self, text, thinking=False, session_id=None):
        if False:
            yield None

    async def history(self, date, limit=None, before=None):
        items = [{"role": "user" if i % 2 == 0 else "odie", "text": f"m{i}", "tools": [], "ts": float(i)} for i in range(50)]
        total = len(items)
        end = before if before is not None else total
        start = max(0, end - limit) if limit else 0
        return {"items": items[start:end], "total": total, "start": start}

    async def close(self):
        pass


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = _store(tmp_path)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c


async def test_history_paging(client):
    r = (await client.get("/api/history", params={"date": "2026-10-01", "limit": 30})).json()
    assert r["total"] == 50 and r["start"] == 20 and len(r["items"]) == 30 and r["items"][-1]["text"] == "m49"
    r2 = (await client.get("/api/history", params={"date": "2026-10-01", "limit": 30, "before": 20})).json()
    assert r2["start"] == 0 and len(r2["items"]) == 20 and r2["items"][0]["text"] == "m0"
    r3 = (await client.get("/api/history", params={"date": "2026-10-01"})).json()
    assert isinstance(r3, dict) and len(r3["items"]) == 50
