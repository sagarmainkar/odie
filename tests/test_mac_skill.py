"""The mac-apps skill: listed on a Mac only; its writes ask; a tool without its app's permission answers with the
Settings line and runs nothing."""
import pytest

from odie.mac import permissions
from odie.skills.registry import BUILTIN, discover, for_this_platform
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_the_skill_is_for_macs_only(store, tmp_path):
    on_mac = {e.name: e for e in discover(store, BUILTIN, tmp_path / "none", system="Darwin")}
    on_linux = {e.name: e for e in discover(store, BUILTIN, tmp_path / "none", system="Linux")}
    assert "mac-apps" in on_mac and "mac-apps" not in on_linux
    assert "documents" in on_mac and "documents" in on_linux
    assert for_this_platform(on_mac["documents"], "Linux") and not for_this_platform(on_mac["mac-apps"], "Linux")


def test_the_tools_and_their_taps(store, tmp_path):
    entry = next(e for e in discover(store, BUILTIN, tmp_path / "none", system="Darwin") if e.name == "mac-apps")
    asks = {t.name: bool(getattr(t, "_require_confirmation", False)) for t in entry.tool_objs}
    assert asks == {"mac_mail_new": False, "mac_mail_read": False, "mac_mail_save_attachment": False, "mac_calendar_events": False,
                    "mac_calendar_add": True, "mac_reminders": False, "mac_reminder_add": True}


async def test_a_tool_without_permission_says_where_to_allow_it(store, tmp_path, monkeypatch):
    entry = next(e for e in discover(store, BUILTIN, tmp_path / "none", system="Darwin") if e.name == "mac-apps")
    tools = {t.name: t for t in entry.tool_objs}
    permissions.forget()
    monkeypatch.setattr(permissions, "_determine", lambda bundle: -1744)
    out = await tools["mac_calendar_events"].func(start="2026-10-21T00:00", end="2026-10-22T00:00")
    assert out == {"error": "Odie isn't allowed to read Calendar yet. Allow it in Settings → Mac apps, then ask again."}
    permissions.forget()


async def test_a_granted_tool_runs_the_app_and_a_bad_time_is_said(store, tmp_path, monkeypatch):
    from odie.mac import calendar
    entry = next(e for e in discover(store, BUILTIN, tmp_path / "none", system="Darwin") if e.name == "mac-apps")
    tools = {t.name: t for t in entry.tool_objs}
    permissions.forget()
    monkeypatch.setattr(permissions, "_determine", lambda bundle: 0)

    async def fake_events(start, end, run=None):
        return [{"id": "u1", "title": "Udo birthday", "start": start.isoformat(), "end": end.isoformat()}]
    monkeypatch.setattr(calendar, "events", fake_events)
    out = await tools["mac_calendar_events"].func(start="2026-10-21T00:00", end="2026-10-22T00:00")
    assert out["events"][0]["title"] == "Udo birthday"
    bad = await tools["mac_calendar_events"].func(start="tomorrow", end="2026-10-22T00:00")
    assert "error" in bad
    permissions.forget()
