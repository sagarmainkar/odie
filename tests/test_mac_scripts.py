"""The AppleScript runner: arguments go as argv, the shared handlers are appended, and osascript's failures become
the three exceptions. Nothing here touches a real app."""
import asyncio
import platform

import pytest

from odie.mac import scripts
from odie.mac.scripts import MacError, MacPermission, MacTimeout, app_in, source


def test_every_script_carries_the_shared_handlers():
    for name in ("probe", "mail_new", "mail_read", "mail_save_attachment", "calendar_events", "calendar_list", "calendar_add",
                 "reminders_due", "reminder_add", "contacts_find"):
        text = source(name)
        assert "on run argv" in text and "on iso(d)" in text and "on q(s)" in text, name


def test_the_app_is_read_out_of_the_permission_error():
    assert app_in("execution error: Not authorized to send Apple events to Calendar. (-1743)", "Mail") == "Calendar"
    assert app_in("something else", "Mail") == "Mail"


class FakeProc:
    def __init__(self, code, out=b"", err=b"", hang=False):
        self.returncode, self.out, self.err, self.hang = code, out, err, hang
        self.killed = False

    async def communicate(self, data=None):
        if self.hang:
            await asyncio.sleep(10)
        return self.out, self.err

    def kill(self):
        self.killed = True


@pytest.mark.skipif(platform.system() != "Darwin", reason="the runner execs osascript")
async def test_the_runner_passes_argv_and_maps_errors(monkeypatch):
    monkeypatch.setattr(scripts, "ALLOWED", True)  # the exec is faked below; nothing real runs
    seen = {}

    def fake_exec(proc):
        async def create(*argv, **kw):
            seen["argv"] = argv
            return proc
        return create

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec(FakeProc(0, out=b'{"ok": 1}\n')))
    assert await scripts.run("probe", "Mail", app="Mail") == '{"ok": 1}'
    assert seen["argv"] == ("osascript", "-", "Mail")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec(FakeProc(1, err=b"Not authorized to send Apple events to Calendar. (-1743)")))
    with pytest.raises(MacPermission) as e:
        await scripts.run("calendar_events", "a", "b", app="Calendar")
    assert str(e.value) == "Calendar"

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec(FakeProc(1, err=b"execution error: no calendar called Work (-2700)")))
    with pytest.raises(MacError) as e:
        await scripts.run("calendar_add", "t", "a", "b", "Work", "", "")
    assert "no calendar called Work" in str(e.value)

    slow = FakeProc(0, hang=True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec(slow))
    with pytest.raises(MacTimeout):
        await scripts.run("mail_new", "x", "25", app="Mail", timeout=0.05)
    assert slow.killed


def test_available_means_macos_with_osascript(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert scripts.available() is False


@pytest.mark.skipif(platform.system() != "Darwin", reason="the runner execs osascript")
async def test_an_app_that_isnt_running_is_opened_hidden_and_asked_again(monkeypatch):
    """Odie runs as a background service, and macOS won't start an app for its Apple events: the app answers
    "isn't running (-600)" (the Allow button for Calendar failed this way). Odie opens it hidden and asks once more."""
    monkeypatch.setattr(scripts, "ALLOWED", True)
    calls = []
    answers = [FakeProc(1, err=b"execution error: Calendar got an error: Application isn\xe2\x80\x99t running. (-600)"),
               FakeProc(0, out=b"ok\n")]

    async def create(*argv, **kw):
        calls.append(argv)
        if argv[0] == "open":
            return FakeProc(0)
        return answers.pop(0)

    async def no_wait(seconds):
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(scripts, "wait_until_running", lambda app: no_wait(0))
    assert await scripts.run("probe", "Calendar", app="Calendar") == "ok"
    assert [argv[0] for argv in calls] == ["osascript", "open", "osascript"]
    assert calls[1] == ("open", "-g", "-j", "-a", "Calendar")


@pytest.mark.skipif(platform.system() != "Darwin", reason="the runner execs osascript")
async def test_an_app_that_still_isnt_running_says_so_once(monkeypatch):
    monkeypatch.setattr(scripts, "ALLOWED", True)
    not_running = b"execution error: Calendar got an error: Application isn\xe2\x80\x99t running. (-600)"

    async def create(*argv, **kw):
        if argv[0] == "open":
            return FakeProc(0)
        return FakeProc(1, err=not_running)

    async def no_wait(app):
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(scripts, "wait_until_running", no_wait)
    with pytest.raises(MacError, match="-600"):
        await scripts.run("probe", "Calendar", app="Calendar")
