"""Permission rows: read without a dialog and cached; asked for on purpose through the probe; a grant remembered for
the times macOS can't say (the app not running)."""
import pytest

from odie.mac import permissions, scripts


@pytest.fixture(autouse=True)
def fresh(isolated_settings):
    permissions.forget()
    yield
    permissions.forget()


def test_codes_become_statuses():
    assert permissions.status_of(0) == "granted"
    assert permissions.status_of(-1743) == "denied"
    assert permissions.status_of(-1744) == "unknown"
    assert permissions.status_of(-600) == "unknown"


def test_status_is_cached_and_unknown_when_macos_cant_say():
    permissions.forget()
    calls = []
    clock = [100.0]

    def determine(bundle):
        calls.append(bundle)
        return 0
    assert permissions.status("mail", determine, now=lambda: clock[0]) == "granted"
    assert permissions.status("mail", determine, now=lambda: clock[0]) == "granted"
    assert calls == ["com.apple.mail"]  # the second read came from the cache
    clock[0] += permissions.CACHE_FOR + 1
    permissions.status("mail", determine, now=lambda: clock[0])
    assert len(calls) == 2

    def broken(bundle):
        raise OSError("no CoreServices")
    permissions.forget()
    assert permissions.status("calendar", broken) == "unknown"
    permissions.forget()


async def test_request_runs_the_probe_and_keeps_the_answer():
    permissions.forget()
    ran = []

    async def allowed(name, *args, app="", timeout=60):
        ran.append((name, args))
        return "ok"
    assert await permissions.request("calendar", run=allowed) == "granted"
    assert ran == [("probe", ("Calendar",))]
    assert permissions.remembered()["calendar"] == "granted"
    assert permissions.status("calendar", determine=lambda b: -1744) == "granted"  # the fresh answer, not a new read

    async def refused(name, *args, app="", timeout=60):
        raise scripts.MacPermission("Reminders")
    assert await permissions.request("reminders", run=refused) == "denied"

    async def broke(name, *args, app="", timeout=60):
        raise scripts.MacError("boom")
    assert await permissions.request("contacts", run=broke) == "unknown"
    permissions.forget()


def test_rows_list_the_shown_apps_in_order_and_hold_contacts_back():
    permissions.forget()
    got = permissions.rows(determine=lambda b: 0 if b == "com.apple.mail" else -1744)
    assert [(r.id, r.status) for r in got] == [("mail", "granted"), ("calendar", "unknown"), ("reminders", "unknown")]
    permissions.forget()


def test_a_remembered_grant_holds_while_the_app_is_closed():
    assert permissions.status("mail", determine=lambda b: -600) == "unknown"  # nothing remembered yet
    permissions.remember("mail", "granted")
    assert permissions.status("mail", determine=lambda b: -600) == "granted"  # Mail closed: the dialog's answer holds
    permissions.forget()
    assert permissions.status("mail", determine=lambda b: -1743) == "denied"  # macOS's own word wins when it has one
    permissions.forget()
    assert permissions.status("mail", determine=lambda b: -1744) == "unknown"  # never asked: the memory is stale
