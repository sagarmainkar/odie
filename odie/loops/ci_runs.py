"""GitHub Actions run mail and the pull request it is about. GitHub's run mail names the repository, the workflow, the
branch and the commit ("[example/app] Run failed: checks - ledger (d0aa897)"), never the pull request, so the same-ID
shortcut and stage 4 couldn't see that it is news for one. Code asks gh which pull request has that branch (and
commit) and puts its name on the mail (Mail.pr); from then on the mail is GitHub's mail about that pull request like
any other (odie.loops.github.refs_in_notification). With no pull request (a push to main, a gh error) it stays a plain
mail: the model may make it his card, never a loop for Odie (odie.loops.ledger.owner_for).

Only GitHub's own address counts, the branch and commit are checked strictly before they reach gh's arguments (built
by code, never a shell), each run is asked once a check, and at most ASK_MOST runs a check."""
from __future__ import annotations

import json
import logging
import re

from odie.loops import github

log = logging.getLogger(__name__)

ASK_MOST = 5  # gh calls a check makes for run mail at most (a burst of CI mail stays a few seconds)
ASK_SECONDS = 15
# "[owner/repo] Run failed: <workflow> - <branch> (<commit>)"; also "PR run failed", "Run cancelled", …
RUN_RE = re.compile(r"^\s*\[([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})\]\s+(?:PR\s+)?run\s+\w+:\s+"
                    r"(.+)\s+-\s+(\S+)\s+\(([0-9a-f]{7,40})\)\s*$", re.IGNORECASE)
BRANCH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/-]{0,199}$")


def run_of(mail) -> tuple[str, str, str] | None:
    """The repository, branch and commit a GitHub Actions run mail names, checked strictly; None for anything else.
      "[example/app] Run failed: checks - ledger (d0aa897)" from notifications@github.com -> ("example/app", "ledger",
        "d0aa897");  the same subject from any other sender -> None;  a branch "--exec=x" or "a..b" -> None;
      "[example/app] Threads newest first (PR #49)" (it names its pull request already) -> None"""
    if not github.is_from_github(getattr(mail, "frm", "") or ""):
        return None
    found = RUN_RE.match(getattr(mail, "subject", "") or "")
    if found is None:
        return None
    owner, repo, _workflow, branch, commit = found.groups()
    if repo in (".", "..") or not BRANCH_RE.match(branch) or ".." in branch or branch.endswith((".", "/")):
        return None
    return f"{owner}/{repo}", branch, commit.lower()


def pick(prs: list, commit: str) -> int | None:
    """Which of the pull requests gh listed for a branch the run was about, or None. Another repository's (a fork's
    branch of the same name) never counts. The one whose head commit is the run's; else the one open pull request (the
    run was on an earlier commit of it); else none.
      [#50 head d0aa897…] and commit d0aa897 -> 50;  [#50 open, head f00…] -> 50;  [#50 merged, head f00…] -> None;
      [#50 open, #51 open], neither head d0aa897 -> None;  [] -> None"""
    own = [p for p in prs if isinstance(p, dict) and not p.get("isCrossRepository")]
    same_head = [p for p in own if str(p.get("headRefOid") or "").lower().startswith(commit)]
    if len(same_head) == 1:
        return int(same_head[0]["number"])
    still_open = [p for p in own if str(p.get("state") or "").upper() == "OPEN"]
    if not same_head and len(still_open) == 1:
        return int(still_open[0]["number"])
    return None


async def pr_for(repo: str, branch: str, commit: str) -> str:
    """The pull request ("example/app#50") whose branch the run was on, from gh, or "" (none, or gh couldn't say)."""
    args = ["pr", "list", "--repo", repo, "--head", branch, "--state", "all",
            "--json", "number,headRefOid,state,isCrossRepository", "--limit", "10"]
    try:
        prs = json.loads(await github.run_gh(args, seconds=ASK_SECONDS) or "[]")
    except (github.GitHubError, ValueError) as e:
        log.info("loops: couldn't find the pull request of a CI run on %s %s: %s", repo, branch, e)
        return ""
    if not isinstance(prs, list):
        return ""
    number = pick(prs, commit)
    if number is None:
        return ""
    ref = github.parse(f"{repo}#{number}")
    if ref is None:
        return ""
    return str(ref)


async def resolve(mails: list) -> None:
    """Puts on each GitHub Actions run mail of this check the pull request it is about (Mail.pr), asking gh once per
    run and at most ASK_MOST times. A mail that isn't a run mail, or a run with no pull request, keeps pr "". """
    asked: dict[tuple[str, str, str], str] = {}
    for mail in mails:
        run = run_of(mail)
        if run is None:
            continue
        if run not in asked:
            if len(asked) >= ASK_MOST:
                continue
            asked[run] = await pr_for(*run)
        mail.pr = asked[run]
