"""'Allow for 30 min': shell commands in one conversation run without a tap, except the ones that must always ask.
The commands below are real ones from a long investigation on 2026-10-04 (paths kept, ids changed)."""
from datetime import datetime, timedelta

import pytest

from odie.agent import shell_grant as g
from odie.store.db import Store

NOW = datetime(2026, 10, 4, 20, 0)

ROUTINE = [
    "sleep 55; ps -p 35432 >/dev/null 2>&1 && echo \"STILL RUNNING\" || echo \"FINISHED\"",
    "tail -30 ~/.agentd/profiles/support-bot/logs/agent.log",
    "ls ~/work/Acme/ 2>/dev/null | head -30",
    "grep -rn \"consume_quota\\|check_quota\" ~/work/billing-service/agents",
    "sed -n '780,830p' ~/work/billing-service/agents/council.py",
    "cat ~/.agentd/profiles/support-bot/skills/support-bot/SKILL.md",
    "find ~/ -maxdepth 3 -type d -iname \"*acme*\" 2>/dev/null",
    "cat > /tmp/acme_ticket.txt <<'EOF'\nInvestigate the credit deduction\nEOF",
    "nohup zsh -i -c 'agentd --profile support-bot chat -q \"$(cat /tmp/acme_ticket.txt)\"' > /tmp/acme_out.txt 2>&1 &",
]

ALWAYS_ASK = [
    "cat ~/.agentd/profiles/support-bot/.env 2>/dev/null",
    "PAT=$(grep SUPABASE_PAT ~/.zshrc 2>/dev/null | sed 's/.*=//')",
    "env | grep -i supabase",
    "kill 35432 2>/dev/null; echo killed",
    "rm -rf ~/work/tmp-build",
    "curl -s -X POST \"https://mcp.supabase.com/mcp?project_ref=abc\" -d '{\"jsonrpc\":\"2.0\"}'",
    "echo hello > ~/notes.txt",
    "sudo launchctl list",
    "git push origin main",
    "python3 -c \"import os; os.remove('x')\"",
    "sed -i '' 's/a/b/' ~/work/app/config.py",
    "cat ~/.zshrc | tail -20",                       # exported keys live there
    "nohup zsh -i -c 'agentd --profile support-bot chat --yolo -q \"check\"' > /tmp/out.txt 2>&1 &",
    "claude --dangerously-skip-permissions -p 'fix it'",
]


@pytest.mark.parametrize("cmd", ROUTINE)
def test_routine_commands_can_run_under_a_grant(cmd):
    assert g.always_ask(cmd) is None, cmd


@pytest.mark.parametrize("cmd", ALWAYS_ASK)
def test_risky_commands_always_ask(cmd):
    assert g.always_ask(cmd), cmd


def test_grant_lasts_thirty_minutes_for_its_conversation_only(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    assert not g.active(s, "chat-2026-10-04-3", NOW)
    g.grant(s, "chat-2026-10-04-3", NOW)
    assert g.active(s, "chat-2026-10-04-3", NOW + timedelta(minutes=29))
    assert not g.active(s, "chat-2026-10-04-3", NOW + timedelta(minutes=31))
    assert not g.active(s, "chat-2026-10-04-4", NOW)  # a New chat starts without it


def test_needs_tap_uses_grant_and_list(tmp_path):
    from types import SimpleNamespace
    s = Store(tmp_path / "a.db")
    s.init_schema()
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-x"))
    check = g.make_check(s, clock=lambda: NOW)
    assert check(command="ls ~", tool_context=ctx) is True            # no grant: ask
    g.grant(s, "chat-x", NOW)
    assert check(command="ls ~", tool_context=ctx) is False           # granted: runs
    assert check(command="cat ~/.env", tool_context=ctx) is True      # still asks
    assert check(command="ls ~", tool_context=None) is True           # no conversation known: ask


async def test_run_shell_tool_asks_adk_per_command_with_the_conversation(tmp_path):
    from types import SimpleNamespace

    from odie.agent.tools.shell import make_shell_tool
    s = Store(tmp_path / "a.db")
    s.init_schema()
    tool = make_shell_tool(home=tmp_path, store=s)
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-y"))
    assert await tool.check_require_confirmation({"command": "ls"}, ctx) is True   # through ADK's own path
    g.grant(s, "chat-y", datetime.now())
    assert await tool.check_require_confirmation({"command": "ls"}, ctx) is False
    assert await tool.check_require_confirmation({"command": "cat .env"}, ctx) is True
    assert "tool_context" not in str(tool._get_declaration())  # the model never sees it
