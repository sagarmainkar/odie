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
                                  "run_query", "slack-post-message", "delete_thread"])
def test_names_that_ask(name):
    assert approvals_mode.asks_by_name(name)


@pytest.mark.parametrize("name", ["gmail_find_email", "calendar_create_event", "list_items", "GMAIL_FETCH_EMAILS"])
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
