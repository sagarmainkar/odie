"""GitHub Actions run mail ("[example/app] Run failed: checks - ledger (d0aa897)") names a workflow, a branch and a
commit, not a pull request. Code finds the pull request with gh (a fake here: the real one is never called), so the
mail is news for that PR's loop; with no pull request it is a plain card for him. And no loop is ever Odie's when Odie
has no work for it (no playbook): it is his card."""
import json
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.loops import ci_runs, consolidate, findings, ledger, migrate, shortcut
from odie.store.db import Store
from odie.watch.fetch import Fetcher, Mail

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
FAKE = __import__("pathlib").Path(__file__).parent.parent / "evals" / "loops" / "fake_gh.py"
HEAD = "d0aa897" + "0" * 33
PR_50 = {"number": 50, "headRefOid": HEAD, "state": "OPEN", "isCrossRepository": False}


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    data_file, log = tmp_path / "gh.json", tmp_path / "gh.log"
    data: dict = {"user": "you-dev"}
    script = tmp_path / "gh"
    script.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    script.chmod(0o755)
    monkeypatch.setenv("ODIE_GH", str(script))
    monkeypatch.setenv("FAKE_GH_DATA", str(data_file))
    monkeypatch.setenv("FAKE_GH_LOG", str(log))

    def save():
        data_file.write_text(json.dumps(data))

    def calls():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]
    save()
    return SimpleNamespace(data=data, save=save, calls=calls)


def ci_mail(mail_id="ci1", subject="[example/app] Run failed: checks - ledger (d0aa897)",
            frm="Your Name <notifications@github.com>"):
    return Mail(id=mail_id, frm=frm, subject=subject, at="2026-11-19T04:20:00Z", snippet="checks: failed",
                attachments=[], source="gmail", body="Run failed for ledger.", thread=f"t-{mail_id}")


def a_check(store, mails, items):
    fetcher = Fetcher(store, NOW)
    for m in mails:
        fetcher._mail[m.id] = m
    return SimpleNamespace(fetcher=fetcher, sent=[], events=[], ahead=[], threads_found=[], mails=mails,
                           report={"findings": items, "line": "", "done": []})


def think_says(*answers):
    async def think(prompt, instruction):
        return json.dumps({"answers": list(answers)})
    return think


LIVE_FINDING = {"ref": "mail:ci1", "title": "Fix CI on PR — Personalities, Pulse", "kind": "pull request",
                "owner": "odie", "why": "checks failed on ledger"}


def test_a_run_mail_is_read_into_its_repo_branch_and_commit():
    assert ci_runs.run_of(ci_mail()) == ("example/app", "ledger", "d0aa897")
    assert ci_runs.run_of(ci_mail(subject="[example/app] PR run failed: CI - feat/x.y (0a1b2c3d)")) == (
        "example/app", "feat/x.y", "0a1b2c3d")
    assert ci_runs.run_of(ci_mail(frm="Mallory <m@evil.example>")) is None  # only GitHub's own address
    assert ci_runs.run_of(ci_mail(subject="[example/app] Run failed: checks - --exec=x (d0aa897)")) is None
    assert ci_runs.run_of(ci_mail(subject="[example/app] Run failed: checks - a..b (d0aa897)")) is None
    assert ci_runs.run_of(ci_mail(subject="[example/app] Threads newest first (PR #49)")) is None


async def test_the_live_ci_mail_joins_its_pull_requests_loop(store, fake_gh):
    fake_gh.data["prs:example/app@ledger"] = [PR_50]
    fake_gh.save()
    pr = ledger.open_loop(store, "", NOW - timedelta(hours=3), "app #50 Personalities, Pulse", "pull request",
                          refs=["example/app#50"], playbook="github-pr", state="waiting")
    mail = ci_mail()
    await ci_runs.resolve([mail, ci_mail("ci2")])  # two mails of one run: one gh call
    assert mail.pr == "example/app#50"
    assert fake_gh.calls() == [["pr", "list", "--repo", "example/app", "--head", "ledger", "--state", "all",
                                "--json", "number,headRefOid,state,isCrossRepository", "--limit", "10"]]
    assert "example/app#50" in shortcut.refs_of(mail)
    assert shortcut.attach_known(store, "", [mail], NOW) == {"ci1": pr}
    found = findings.collect(a_check(store, [mail], [LIVE_FINDING]))
    await consolidate.consolidate(store, "", NOW, found, think_says({"f": "F1", "is": "new", "owner": "odie"}), {})
    assert [loop["id"] for loop in ledger.open_loops(store, "")] == [pr]  # no orphan beside it


async def test_with_no_loop_yet_the_ci_mail_opens_the_pull_requests_own_loop(store, fake_gh):
    fake_gh.data["prs:example/app@ledger"] = [{**PR_50, "headRefOid": "f" * 40}]  # ran on an older commit, still open
    fake_gh.save()
    mail = ci_mail()
    await ci_runs.resolve([mail])
    found = findings.collect(a_check(store, [mail], [LIVE_FINDING]))
    answer = {"f": "F1", "is": "new", "title": "Fix CI on PR", "kind": "ci failure", "owner": "odie"}
    await consolidate.consolidate(store, "", NOW, found, think_says(answer), {})
    (loop,) = ledger.open_loops(store, "")
    assert loop["playbook"] == "github-pr" and "example/app#50" in loop["refs"] and loop["kind"] == "pull request"


@pytest.mark.parametrize("prs", [[], "error", [{**PR_50, "headRefOid": "f" * 40, "state": "MERGED"}],
                                 [{**PR_50, "isCrossRepository": True}]])
async def test_a_ci_mail_with_no_pull_request_is_his_card(store, fake_gh, prs):
    if prs != "error":
        fake_gh.data["prs:example/app@ledger"] = prs
    fake_gh.save()
    mail = ci_mail()
    await ci_runs.resolve([mail])
    assert mail.pr == ""
    found = findings.collect(a_check(store, [mail], [LIVE_FINDING]))
    await consolidate.consolidate(store, "", NOW, found, think_says({"f": "F1", "is": "new", "owner": "odie"}), {})
    (loop,) = ledger.open_loops(store, "")
    assert (loop["owner"], loop["state"], loop["playbook"]) == ("you", "ready", "")


async def test_gh_is_asked_at_most_a_few_times_a_check(store, fake_gh):
    mails = [ci_mail(f"c{i}", subject=f"[example/app] Run failed: checks - b{i} (d0aa89{i})") for i in range(9)]
    await ci_runs.resolve(mails)
    assert len(fake_gh.calls()) == ci_runs.ASK_MOST


def test_odie_owns_a_loop_only_when_it_has_work_for_it():
    assert ledger.owner_for("odie", "github-pr") == "odie"
    assert ledger.owner_for("odie", "") == "you"
    assert ledger.owner_for("them", "") == "them"
    assert ledger.owner_for("you", "") == "you"


async def test_an_answer_keeping_odie_on_a_plain_loop_makes_it_his_card(store):
    lid = ledger.open_loop(store, "", NOW, "Pay gas bill", "bill", owner="them", refs=["mail:g1"], state="waiting")
    mail = Mail(id="g2", frm="Gas <bills@gas.example>", subject="Gas bill", at="", snippet="", attachments=[],
                source="gmail")
    found = findings.collect(a_check(store, [mail], [{"ref": "mail:g2", "title": "Gas bill", "owner": "odie"}]))
    await consolidate.consolidate(store, "", NOW, found,
                                  think_says({"f": "F1", "is": "same", "loop": lid, "owner": "odie"}), {})
    loop = ledger.get(store, lid)
    assert (loop["owner"], loop["state"]) == ("you", "ready")


def test_the_upgrade_gives_him_every_open_orphan_once(store):
    orphan = ledger.open_loop(store, "", NOW, "Fix CI on PR", "pull request", owner="odie", refs=["mail:ci1"],
                              state="waiting")
    pr = ledger.open_loop(store, "", NOW, "app #50", "pull request", owner="odie", refs=["example/app#50"],
                          playbook="github-pr", state="waiting")
    closed = ledger.open_loop(store, "", NOW, "Old", "pull request", owner="odie", refs=["mail:o1"], state="waiting")
    ledger.close(store, closed, NOW, "odie", "done")
    lines = migrate.no_orphans_once(store, NOW)
    assert len(lines) == 1
    got = ledger.get(store, orphan)
    assert (got["owner"], got["state"], bool(got["shown_at"])) == ("you", "ready", True)
    assert ledger.get(store, pr)["owner"] == "odie" and ledger.get(store, pr)["state"] == "waiting"
    assert ledger.get(store, closed)["owner"] == "odie"
    assert migrate.no_orphans_once(store, NOW + timedelta(hours=1)) is None  # the second start: nothing
    assert ledger.get(store, orphan)["updated_at"] == got["updated_at"]
