"""Updating Odie from the app: the check, its cache, and the two routes."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from odie import update


@pytest.fixture
def git_calls(monkeypatch):
    """A fake git: records the calls, answers rev-parse with what the test set in `heads` and `tag -l` with `tags`.
    The install follows main unless a test sets ODIE_BRANCH itself."""
    calls: list[tuple[str, ...]] = []
    heads = {"origin/main": "b" * 40, "HEAD": "a" * 40, "v0.2.0^{commit}": "c" * 40}
    tags: list[str] = []
    monkeypatch.setenv("ODIE_BRANCH", "main")

    async def fake(*args: str, timeout: float = 30) -> str:
        calls.append(args)
        if args[0] == "rev-parse":
            return heads[args[1]]
        if args[:2] == ("tag", "-l"):
            return "\n".join(tags)
        return ""

    monkeypatch.setattr(update, "_git", fake)
    monkeypatch.setattr(update, "_last_check", None)
    return calls, heads, tags


def test_is_fresh_reuses_a_recent_answer_unless_forced():
    last = {"checked_at": 1000.0}
    assert update.is_fresh(last, 1000.0 + 180, force=False)
    assert not update.is_fresh(last, 1000.0 + 660, force=False)
    assert not update.is_fresh(last, 1000.0 + 60, force=True)
    assert not update.is_fresh(None, 1000.0, force=False)


async def test_check_compares_head_with_origin_and_caches(git_calls):
    calls, heads, _ = git_calls
    first = await update.check()
    assert first["behind"] is True and first["current"] == "aaaaaaa" and first["latest"] == "bbbbbbb"
    assert calls[0][0] == "fetch"
    again = await update.check()
    assert again is first and len(calls) == 3  # no second fetch within CHECK_EVERY
    heads["origin/main"] = heads["HEAD"]
    forced = await update.check(force=True)
    assert forced["behind"] is False and len(calls) == 6


async def test_check_following_releases_compares_with_the_newest_tag(git_calls, monkeypatch):
    calls, _, tags = git_calls
    monkeypatch.setenv("ODIE_BRANCH", "releases")
    tags += ["v0.1.0", "v0.2.0"]
    found = await update.check()
    assert found["behind"] is True and found["latest"] == "ccccccc"
    assert ("rev-parse", "v0.2.0^{commit}") in calls


async def test_check_with_no_release_yet_is_up_to_date(git_calls, monkeypatch):
    monkeypatch.setenv("ODIE_BRANCH", "releases")
    found = await update.check()
    assert found["behind"] is False and found["latest"] == found["current"]


def test_can_update_only_from_the_installed_checkout(monkeypatch, tmp_path):
    class Inst:
        app = tmp_path / "app"
    monkeypatch.setattr(update, "install", lambda: Inst)
    monkeypatch.setattr(update, "CODE_DIR", tmp_path / "app")
    assert not update.can_update()  # no .git: not a checkout
    (tmp_path / "app" / ".git").mkdir(parents=True)
    assert update.can_update()
    monkeypatch.setattr(update, "CODE_DIR", tmp_path / "elsewhere")
    assert not update.can_update()  # the server runs other code than the install


def test_version_is_a_short_commit_here_and_unknown_without_git(monkeypatch):
    monkeypatch.setattr(update, "_version", None)
    assert len(update.version()) == 7
    monkeypatch.setattr(update, "_version", None)
    monkeypatch.setattr(update, "CODE_DIR", Path("/nowhere"))
    assert update.version() == "unknown"


def test_start_runs_the_odie_command_detached(monkeypatch, tmp_path):
    class Inst:
        app = tmp_path / "app"
        logs = tmp_path / "logs"
        update_log = tmp_path / "logs" / "update.log"
    monkeypatch.setattr(update, "install", lambda: Inst)
    monkeypatch.setattr(update, "_version", "aaaaaaa")  # so the log line doesn't ask git through the fake Popen
    seen: dict = {}

    class FakeProc:
        pid = 4242
        def poll(self):
            return None
    def popen(args, **kw):
        seen.update(args=args, **kw)
        return FakeProc()
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert update.start() == 4242
    assert seen["args"][1:] == ["-P", "-m", "odie.cli", "update"] and seen["start_new_session"] is True
    assert seen["cwd"] == Inst.app and update.running()
    monkeypatch.setattr(update, "_started", None)
    assert not update.running()
