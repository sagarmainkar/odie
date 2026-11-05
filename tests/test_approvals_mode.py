"""The approvals mode: Careful (every tap as today) or Smart (routine work runs, risky things still ask)."""
from pathlib import Path

import pytest

from odie import approvals_mode
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def test_default_is_careful(store):
    assert approvals_mode.mode(store) == approvals_mode.CAREFUL
    assert not approvals_mode.is_smart(store)


def test_unknown_saved_value_reads_as_careful(store):
    store.set_setting(approvals_mode.KEY, "reckless")
    assert approvals_mode.mode(store) == approvals_mode.CAREFUL
    store.set_setting(approvals_mode.KEY, {"mode": "smart"})  # not even a string
    assert approvals_mode.mode(store) == approvals_mode.CAREFUL


def test_set_and_get(store):
    assert approvals_mode.set_mode(store, "smart") == "smart"
    assert approvals_mode.mode(store) == "smart"
    assert approvals_mode.is_smart(store)
    approvals_mode.set_mode(store, "careful")
    assert approvals_mode.mode(store) == "careful"


def test_set_refuses_an_unknown_value_and_keeps_the_old_one(store):
    approvals_mode.set_mode(store, "smart")
    with pytest.raises(ValueError):
        approvals_mode.set_mode(store, "yolo")
    assert approvals_mode.mode(store) == "smart"


def test_set_is_audited(store):
    approvals_mode.set_mode(store, "smart")
    rows = store.query("select actor, event, result_summary from audit_log where event = 'approvals_mode'")
    assert [tuple(r) for r in rows] == [("user", "approvals_mode", "smart")]


@pytest.mark.parametrize("name", ["GMAIL_SEND_EMAIL", "cancel_order", "shareLink", "COMPOSIO_MULTI_EXECUTE_TOOL",
                                  "run_query", "slack-post-message", "delete_thread", "GMAIL_FORWARD_MESSAGE", "transfer_funds",
                                  "STRIPE_CREATE_REFUND", "drive_upload_file", "export_contacts", "invite_user", "submit_form",
                                  "set_password"])
def test_names_that_ask(name):
    assert approvals_mode.asks_by_name(name)


@pytest.mark.parametrize("name", ["gmail_find_email", "list_events", "list_items", "GMAIL_FETCH_EMAILS", "get_weather", "search_notes"])
def test_names_that_do_not_ask(name):
    assert not approvals_mode.asks_by_name(name)


def test_plain_write_needs_a_tap_only_in_careful(store):
    assert approvals_mode.plain_write_needs_tap(store)
    approvals_mode.set_mode(store, "smart")
    assert not approvals_mode.plain_write_needs_tap(store)
    approvals_mode.set_mode(store, "careful")
    assert approvals_mode.plain_write_needs_tap(store)


def test_install_skill_and_addon_gated_tools_still_ask_in_smart(store):
    """Smart reads nothing in these tools' own gates: install_skill is built with require_confirmation=True, and an
    add-on's gated tools are listed by gated_tools() (the runner and background guard read that list), whatever the mode."""
    from google.adk.tools import FunctionTool

    from odie import addons
    from odie.addons import Addon
    from odie.agent.agent import GATED_TOOLS
    from odie.skills import builder
    from odie.skills.registry import _load_tools

    async def unlock_door() -> str:
        """Unlock the door."""
        return "unlocked"

    approvals_mode.set_mode(store, "smart")
    addons.use([Addon("bell", tool_names=frozenset({"unlock_door"}), gated=frozenset({"unlock_door"}),
                      tools=lambda s: [FunctionTool(unlock_door, require_confirmation=True)])])
    try:
        skill_tools = {t.name: t for t in _load_tools(Path(builder.__file__).parent / "skill-builder", "skill-builder")}
        assert skill_tools["install_skill"]._require_confirmation is True
        assert {"run_shell", "install_skill"} <= GATED_TOOLS
        assert addons.gated_tools() == frozenset({"unlock_door"})
        built = {t.name: t for t in addons.tools_of(addons.active()[0], store)}
        for name in addons.gated_tools():
            assert built[name]._require_confirmation is True, name
    finally:
        addons.use(None)


def test_the_context_line_names_the_mode(store):
    assert approvals_mode.context_line(store) == "Approvals: careful (changes ask first)"
    approvals_mode.set_mode(store, "smart")
    line = approvals_mode.context_line(store)
    assert line.startswith("Approvals: smart (") and "secrets still ask" in line


def test_the_trailer_carries_the_mode_line_per_turn(store):
    """The static prompt is untouched: the line rides on each turn's context, so a flip shows on the next message."""
    from datetime import datetime

    from odie.agent.prompt import build_turn_context
    now = datetime(2026, 11, 5, 14, 16)
    before = build_turn_context(now, "", "", approvals=approvals_mode.context_line(store))
    approvals_mode.set_mode(store, "smart")
    after = build_turn_context(now, "", "", approvals=approvals_mode.context_line(store))
    assert "now 14:16 Thu 5 Nov · Approvals: careful (changes ask first)]" in before
    assert "· Approvals: smart (" in after
    assert "Approvals" not in build_turn_context(now, "", "")


@pytest.mark.parametrize("name", [
    "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL", "SLACK_SCHEDULE_MESSAGE", "DISCORD_CREATE_MESSAGE", "GITHUB_CREATE_AN_ISSUE_COMMENT",
    "GITHUB_CREATE_A_PULL_REQUEST", "GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE", "GOOGLEDRIVE_CREATE_PERMISSION",
    "STRIPE_CREATE_PAYMENT_INTENT", "STRIPE_CREATE_CHARGE", "PAYPAL_CREATE_PAYOUT", "UBER_REQUEST_RIDE", "DOORDASH_CREATE_DELIVERY",
    "OPENTABLE_CREATE_RESERVATION", "reserve_table", "COMPOSIO_REMOTE_WORKBENCH", "COMPOSIO_REMOTE_BASH_TOOL", "python_exec",
    "exec_command", "eval_code", "bash", "shell", "HTTP_REQUEST", "GOOGLECALENDAR_CREATE_EVENT", "GOOGLECALENDAR_UPDATE_EVENT",
    "calendar_create_event", "add_meeting",
])
def test_more_real_names_that_ask(name):
    assert approvals_mode.asks_by_name(name), name


def test_mail_read_this_turn_and_runs_free(store):
    approvals_mode.set_mode(store, "smart")
    assert approvals_mode.runs_free(store, "chat-1") is True
    assert approvals_mode.runs_free(store, None) is False or approvals_mode.mail_read_this_turn(store, None) is False
    store.audit("user", "message", result_summary="hi", session_id="chat-1")
    store.audit("agent", "mail_seen", args={"from": "a@example.com", "subject": "Invoice"}, session_id="chat-1")
    assert approvals_mode.mail_read_this_turn(store, "chat-1") is True
    assert approvals_mode.runs_free(store, "chat-1") is False  # Smart, but a mail was read this turn: ask again
    store.audit("user", "message", result_summary="next", session_id="chat-1")
    assert approvals_mode.mail_read_this_turn(store, "chat-1") is False  # the mail was last turn
    assert approvals_mode.runs_free(store, "chat-1") is True
    approvals_mode.set_mode(store, "careful")
    assert approvals_mode.runs_free(store, "chat-1") is False
