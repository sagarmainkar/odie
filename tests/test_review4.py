import asyncio
from types import SimpleNamespace

from odie.app.runner import approval_from_confirmation
from odie.store.db import Store


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def _fc(tool, args, rid="req"):
    return SimpleNamespace(id=rid, name="adk_request_confirmation", args={"originalFunctionCall": {"id": "c", "name": tool, "args": args}, "toolConfirmation": {}})


def test_provenance_from_audit_flags_mail_seen_in_window(tmp_path):
    s = _store(tmp_path)
    s.audit("user", "message", result_summary="hi", session_id="chat-1")
    s.log_mail_seen("chat-1", "inv0", "IT Support <h@acme-support.example>", "Quota", via="gmail_search")
    s.audit("user", "message", result_summary="now send it", session_id="chat-1")  # next turn, no mail read in it
    a = approval_from_confirmation(_fc("gmail_trash", {"message_id": "m1"}), "inv1", "chat-1", s)
    assert a["risk"] == "mail_earlier" and a["provenance"][0]["from"].startswith("IT Support")  # previous turn: soft note


def test_shell_card_shows_cwd(tmp_path):
    s = _store(tmp_path)
    a = approval_from_confirmation(_fc("run_shell", {"command": "git clean -fdx", "cwd": "~/work/x"}), "i", "c", s)
    assert a["summary"] == "Run in ~/work/x: git clean -fdx" and a["detail"]["cwd"] == "~/work/x"
    b = approval_from_confirmation(_fc("run_shell", {"command": "uptime"}), "i", "c", s)
    assert b["summary"] == "Run in ~: uptime"


async def test_shell_kills_runaway_output(tmp_path):
    from odie.agent.tools.shell import make_shell_tool
    tool = make_shell_tool(home=tmp_path)
    t0 = asyncio.get_event_loop().time()
    out = await asyncio.wait_for(tool.func(command="python3 -c \"import sys\nwhile True: sys.stdout.write('x'*1000+'\\n'); sys.stdout.flush()\"", cwd=str(tmp_path)), 20)
    assert len(out) <= 8300 and "…" in out and asyncio.get_event_loop().time() - t0 < 15


async def test_reconcile_unfinished_approvals(isolated_settings, tmp_path):
    from odie.app.runner import OdieRunner
    s = _store(tmp_path)
    r = OdieRunner(s)
    posted, kinds = [], []

    async def fake_post(text, session_id=None, kind="system"):
        posted.append(text)
        kinds.append(kind)
    r.post_message = fake_post
    lost = s.create_approval("chat-1", "inv1", "req1", "gmail_send_draft", {"draft_id": "d1"}, summary="Send email to a@x · S1", detail={}, provenance=[])
    s.decide_approval(lost, True)
    done = s.create_approval("chat-1", "inv2", "req2", "run_shell", {"command": "uptime"}, summary="Run in ~: uptime", detail={}, provenance=[])
    s.decide_approval(done, True)
    s.audit("agent", "tool_call", tool="run_shell", args={"command": "uptime"}, result_summary="up", session_id="chat-1", invocation_id="inv2")
    n = await r.reconcile_approvals()
    assert n == 1 and posted and "never got to" in posted[0] and "Send email to a@x" in posted[0]
    assert kinds == ["reply"]  # the Mac shows it as a reply that came late, not as housekeeping
    assert s.get_approval(lost)["result_text"].startswith("Not done") and s.get_approval(done)["result_text"] == "Completed."
    assert await r.reconcile_approvals() == 0
    await r.close()
