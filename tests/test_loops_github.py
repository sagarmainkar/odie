"""GitHub references are checked strictly before code uses them, and `gh` is called only with arguments code built
(proactive design §7: the model proposes, the rail permits). A fake `gh` answers; the real one is never called."""
import json
import sys
from types import SimpleNamespace

import pytest

from odie.loops import github

FAKE = __import__("pathlib").Path(__file__).parent.parent / "evals" / "loops" / "fake_gh.py"
OPEN_PR = {"number": 49, "title": "Threads newest first", "state": "OPEN", "isDraft": False, "mergedAt": None,
           "closedAt": None, "author": {"login": "asha-dev"}, "headRefName": "threads-newest", "baseRefName": "main",
           "additions": 41, "deletions": 9, "changedFiles": 3, "isCrossRepository": False, "reviewDecision": "",
           "url": "https://github.com/example/app/pull/49",
           "statusCheckRollup": [{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
                                 {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"}]}


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    """Points Odie's `gh` at the fake; returns (data, calls) to fill and read."""
    data_file, log = tmp_path / "gh.json", tmp_path / "gh.log"
    data: dict = {"user": "asha-dev"}
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


def test_a_ref_is_checked_strictly():
    assert github.parse("example/app#49") == github.Ref("example", "app", 49)
    assert github.parse("Example-Org/my.app_2#7") == github.Ref("Example-Org", "my.app_2", 7)
    for bad in ("example/app#0", "example/app#49; rm -rf /", "-x/app#1", "example/../app#1", "example/..#1",
                "example/app", "example/app#1e3", "a/b/c#1", "example/app#12345678", "--repo/x#1", "", "example/ app#1"):
        assert github.parse(bad) is None, bad


def test_the_link_is_built_by_code():
    ref = github.Ref("example", "app", 49)
    assert github.link(ref, "pull request") == "https://github.com/example/app/pull/49"
    assert github.link(ref, "issue") == "https://github.com/example/app/issues/49"


def test_a_notification_mail_names_its_pull_request():
    mail = SimpleNamespace(frm="Asha <notifications@github.com>", subject="Re: [example/app] Threads newest first (PR #49)")
    assert github.refs_in_notification(mail) == ["example/app#49"]
    issue = SimpleNamespace(frm="notifications@github.com", subject="[example/app] Crash on start (Issue #7)")
    assert github.refs_in_notification(issue) == ["example/app#7"]
    lookalike = SimpleNamespace(frm="news@github-deals.example", subject="[example/app] Win big (PR #49)")
    assert github.refs_in_notification(lookalike) == []  # not GitHub's own sender: no shortcut
    odd = SimpleNamespace(frm="notifications@github.com", subject="[example/app; rm -rf ~] x (PR #49)")
    assert github.refs_in_notification(odd) == []


async def test_pr_facts_runs_gh_with_arguments_code_built(fake_gh):
    fake_gh.data["pr:example/app#49"] = OPEN_PR
    fake_gh.save()
    got = await github.pr_facts(github.Ref("example", "app", 49))
    call = fake_gh.calls()[0]
    assert call[:5] == ["pr", "view", "49", "--repo", "example/app"] and call[5] == "--json"
    assert got["state"] == "open" and got["checks"] == "green" and got["files"] == 3 and got["from_fork"] is False
    assert github.headline(got) == "Open · CI green · 3 files, +41 −9"


async def test_merged_and_draft_headlines(fake_gh):
    fake_gh.data["pr:example/app#50"] = {**OPEN_PR, "number": 50, "state": "MERGED", "mergedAt": "2026-11-18T15:34:00Z"}
    fake_gh.data["pr:example/app#51"] = {**OPEN_PR, "number": 51, "isDraft": True,
                                         "statusCheckRollup": [{"name": "tests", "status": "IN_PROGRESS", "conclusion": ""}]}
    fake_gh.save()
    merged = await github.pr_facts(github.Ref("example", "app", 50))
    assert merged["state"] == "merged" and github.headline(merged).startswith("Merged ")
    draft = await github.pr_facts(github.Ref("example", "app", 51))
    assert github.headline(draft) == "Draft · CI running · 3 files, +41 −9"


async def test_issue_facts_say_whether_it_is_assigned_to_you(fake_gh):
    fake_gh.data["issue:example/app#7"] = {"number": 7, "title": "Crash on start", "state": "OPEN", "closedAt": None,
                                           "author": {"login": "priya"}, "assignees": [{"login": "someone-else"}],
                                           "labels": [{"name": "bug"}], "url": "https://github.com/example/app/issues/7"}
    fake_gh.save()
    got = await github.issue_facts(github.Ref("example", "app", 7))
    assert got["assigned_to_you"] is False and got["state"] == "open" and got["you"] == "asha-dev"


async def test_a_gh_failure_is_a_plain_error(fake_gh):
    with pytest.raises(github.GitHubError):
        await github.pr_facts(github.Ref("example", "app", 404))


async def test_no_gh_installed_is_a_plain_error(monkeypatch):
    monkeypatch.setenv("ODIE_GH", "/nonexistent/gh")
    with pytest.raises(github.GitHubError):
        await github.pr_facts(github.Ref("example", "app", 1))


async def test_pr_facts_say_whether_it_is_yours_and_whether_your_review_is_asked(fake_gh):
    fake_gh.data["user"] = "you-dev"
    fake_gh.data["pr:example/app#49"] = {**OPEN_PR, "reviewRequests": [{"login": "you-dev"}, {"name": "core-team"}]}
    fake_gh.data["pr:example/app#60"] = {**OPEN_PR, "number": 60, "author": {"login": "you-dev"}, "reviewRequests": []}
    fake_gh.save()
    asked = await github.pr_facts(github.Ref("example", "app", 49))
    assert asked["you"] == "you-dev" and asked["yours"] is False and asked["review_asked_of_you"] is True
    own = await github.pr_facts(github.Ref("example", "app", 60))
    assert own["yours"] is True and own["review_asked_of_you"] is False
