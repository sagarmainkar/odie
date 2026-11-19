"""GitHub, read-only, for the github-pr playbook (proactive design §7). The model names a pull request or an issue
("example/app#49"); code checks the name strictly (parse) and builds every `gh` command itself, so nothing the model
or a mail wrote ever reaches a command line. Facts come back as a small fixed dict, and a one-line headline for the
card is written from them by code.

`gh` is the GitHub CLI, signed in by the user; ODIE_GH names another one (tests point it at a fake)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime

GH_SECONDS = 30
# owner: letters, digits and single hyphens, not starting with one (GitHub's rule), at most 39; repo: letters, digits,
# ".", "_" and "-", at most 100, never "." or ".."; number: 1 to 7 digits, not starting with 0.
REF_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})#([1-9][0-9]{0,6})$")
NOTIFICATION_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100})\].*\((?:PR |Issue )?#([1-9][0-9]{0,6})\)")
GITHUB_SENDERS = ("notifications@github.com", "noreply@github.com")
PR_FIELDS = ("number,title,state,isDraft,mergedAt,closedAt,author,headRefName,headRefOid,baseRefName,additions,deletions,"
             "changedFiles,files,commits,isCrossRepository,reviewDecision,reviewRequests,url,statusCheckRollup")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PATHS_KEPT = 300  # file paths kept from a pull request's facts (the rail reads them; a huge one is cut)
DIFF_MOST = 12000  # characters of a diff the brief reads
CLONE_SECONDS = 300
ISSUE_FIELDS = "number,title,state,closedAt,author,assignees,labels,url"


class GitHubError(Exception):
    """gh couldn't answer (not installed, not signed in, no such pull request): said in plain words."""


@dataclass(frozen=True)
class Ref:
    owner: str
    repo: str
    number: int

    @property
    def repo_path(self) -> str:
        return f"{self.owner}/{self.repo}"

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


def parse(text: str) -> Ref | None:
    """A pull request's or an issue's name, checked strictly; None for anything else.
      "example/app#49" -> Ref(example, app, 49);  "example/app#49; rm -rf /" -> None;  "-x/app#1" -> None;
      "example/..#1" -> None;  "example/app" (no number) -> None"""
    found = REF_RE.match((text or "").strip())
    if found is None:
        return None
    owner, repo, number = found.groups()
    if repo in (".", ".."):
        return None
    return Ref(owner, repo, int(number))


def link(ref: Ref, kind: str) -> str:
    """The page on GitHub, built from a checked ref: a pull request -> .../pull/49; an issue -> .../issues/49."""
    if "issue" in (kind or "").lower():
        return f"https://github.com/{ref.repo_path}/issues/{ref.number}"
    return f"https://github.com/{ref.repo_path}/pull/{ref.number}"


def is_from_github(frm: str) -> bool:
    """Whether a mail comes from GitHub's own notification address. "Asha <notifications@github.com>" -> True;
    "news@github-deals.example" -> False."""
    address = (frm or "").split("<")[-1].strip(" >").lower()
    return address in GITHUB_SENDERS


def refs_in_notification(mail) -> list[str]:
    """The pull request or issue a GitHub notification mail is about, from its subject, for the same-ID shortcut
    (design §3): "[example/app] Threads newest first (PR #49)" from notifications@github.com -> ["example/app#49"];
    a run mail ("Run failed: checks - ledger (d0aa897)") whose pull request code found (Mail.pr) -> ["example/app#50"];
    any other sender, or a subject that doesn't check out -> []."""
    if not is_from_github(getattr(mail, "frm", "")):
        return []
    found = NOTIFICATION_RE.search(getattr(mail, "subject", "") or "")
    if found is None:
        resolved = parse(getattr(mail, "pr", "") or "")  # a CI run mail: code asked gh (odie.loops.ci_runs)
        if resolved is None:
            return []
        return [str(resolved)]
    ref = parse(f"{found.group(1)}#{found.group(2)}")
    if ref is None:
        return []
    return [str(ref)]


def gh_path() -> str | None:
    """The gh to run: ODIE_GH when set, else the one on PATH; None when there is none."""
    named = os.environ.get("ODIE_GH")
    if named:
        return named
    return shutil.which("gh")


async def run_gh(args: list[str], seconds: float | None = None) -> str:
    """Runs gh with these arguments (built by code: never text from the model or a mail) and returns what it printed.
    Not installed, a failure or over `seconds` (GH_SECONDS unless a clone) -> GitHubError."""
    if seconds is None:
        seconds = GH_SECONDS
    gh = gh_path()
    if gh is None or not os.path.exists(gh):
        raise GitHubError("The GitHub CLI (gh) isn't installed here.")
    proc = await asyncio.create_subprocess_exec(gh, *args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), seconds)
    except TimeoutError:
        _stop_group(proc)
        await proc.wait()  # reaped, so no stopped gh is left behind
        raise GitHubError(f"gh took longer than {int(seconds)} seconds.")
    except asyncio.CancelledError:
        _stop_group(proc)  # its job was stopped: gh, and the git and ssh a clone started, stop with it
        raise
    if proc.returncode != 0:
        raise GitHubError((err.decode(errors="replace").strip() or "gh failed")[:300])
    return out.decode(errors="replace")


def _stop_group(proc) -> None:
    """Stops gh and everything it started (it runs in its own process group); one already gone is fine."""
    import signal
    pid = getattr(proc, "pid", None)
    try:
        if pid is None:
            raise ProcessLookupError
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def checks_of(rollup: list | None) -> str:
    """CI in one word from GitHub's status checks: all passed -> "green"; any failed -> "red"; any still running ->
    "running"; none -> "none"."""
    rows = rollup or []
    if not rows:
        return "none"
    outcomes = []
    for row in rows:
        conclusion = str(row.get("conclusion") or row.get("state") or "").upper()
        status = str(row.get("status") or "").upper()
        outcomes.append((status, conclusion))
    if any(c in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED") for _, c in outcomes):
        return "red"
    if any(s not in ("", "COMPLETED") or c in ("", "PENDING", "EXPECTED") for s, c in outcomes):
        return "running"
    return "green"


def _login(person) -> str:
    if isinstance(person, dict):
        return str(person.get("login") or "")
    return ""


async def pr_facts(ref: Ref) -> dict:
    """Step pr_facts (tier 0): `gh pr view <n> --repo <owner/repo> --json …`, reduced to the facts the brief and the
    card use, with whose it is: `yours` (the signed-in user wrote it) and `review_asked_of_you`."""
    raw = json.loads(await run_gh(["pr", "view", str(ref.number), "--repo", ref.repo_path, "--json", PR_FIELDS]))
    state = str(raw.get("state") or "").lower()
    you = await whoami()
    author = _login(raw.get("author"))
    asked = [_login(r) for r in raw.get("reviewRequests") or []]  # a team's request has no login
    paths = [str(f.get("path") or "") for f in raw.get("files") or [] if isinstance(f, dict)][:PATHS_KEPT]
    commit_authors = [first_author(c) for c in raw.get("commits") or [] if isinstance(c, dict)]
    head_sha = str(raw.get("headRefOid") or "")
    if not SHA_RE.match(head_sha):
        head_sha = ""
    return {"ref": str(ref), "kind": "pull request", "title": str(raw.get("title") or "")[:200], "state": state,
            "you": you, "yours": bool(you) and author == you, "review_asked_of_you": bool(you) and you in asked,
            "draft": bool(raw.get("isDraft")), "merged_at": raw.get("mergedAt"), "closed_at": raw.get("closedAt"),
            "author": author, "head": str(raw.get("headRefName") or ""),
            "base": str(raw.get("baseRefName") or ""), "additions": int(raw.get("additions") or 0),
            "deletions": int(raw.get("deletions") or 0), "files": int(raw.get("changedFiles") or 0),
            "from_fork": bool(raw.get("isCrossRepository")), "review": str(raw.get("reviewDecision") or ""),
            "checks": checks_of(raw.get("statusCheckRollup")), "url": link(ref, "pull request"),
            "head_sha": head_sha, "paths": paths, "on_your_repo": is_own_repo(ref, you), "commit_authors": commit_authors}


def first_author(commit: dict) -> str:
    """A commit's author's GitHub login (its first author: co-authors named in its message come after), or "" when
    GitHub knows no account for them: {"authors": [{"login": "asha-dev"}, {"login": ""}]} -> "asha-dev"; none -> ""."""
    authors = commit.get("authors") or []
    if not authors or not isinstance(authors[0], dict):
        return ""
    return str(authors[0].get("login") or "")


def is_own_repo(ref: Ref, you: str) -> bool:
    """Whether the repo belongs to the signed-in login (its owner is them, as GitHub compares names: any case):
    asha-dev/app with you "asha-dev" -> True; "Asha-Dev" -> True; example/app -> False; nobody signed in -> False."""
    return bool(you) and ref.owner.lower() == you.lower()


async def pushers(ref: Ref) -> list[str] | None:
    """Every account that can push to the repo (tier 0): `gh api repos/<owner/repo>/collaborators --paginate --jq
    [.[] | select(.permissions.push) | .login]`; None when GitHub won't say (then the rail refuses to test)."""
    try:
        text = await run_gh(["api", f"repos/{ref.repo_path}/collaborators", "--paginate", "--jq",
                             "[.[] | select(.permissions.push) | .login]"])
    except GitHubError:
        return None
    logins = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            page = json.loads(line)
        except ValueError:
            return None
        if not isinstance(page, list):
            return None
        logins += [str(x) for x in page]
    return logins


async def write_keys(ref: Ref) -> list[str] | None:
    """The repo's deploy keys that can push (tier 0): `gh api repos/<r>/keys`, those with read_only false; None when
    GitHub won't say (then the rail refuses to test). A key that can write could have pushed to his branch."""
    try:
        text = await run_gh(["api", f"repos/{ref.repo_path}/keys", "--paginate", "--jq",
                             "[.[] | select(.read_only == false) | .title]"])
    except GitHubError:
        return None
    return _json_pages(text)


async def unsigned_commits(ref: Ref, you: str) -> list[str] | None:
    """The pull request's commits GitHub doesn't show as signed and verified by him (tier 0; only asked when he chose
    "signed commits only"): `gh api repos/<r>/pulls/<n>/commits`; short shas, or None when GitHub won't say."""
    try:
        text = await run_gh(["api", f"repos/{ref.repo_path}/pulls/{ref.number}/commits", "--paginate", "--jq",
                             "[.[] | {sha: .sha, verified: .commit.verification.verified, login: (.author.login // \"\")}]"])
    except GitHubError:
        return None
    rows = _json_pages(text)
    if rows is None:
        return None
    out = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        his = str(row.get("login") or "").lower() == (you or "").lower() and bool(you)
        if row.get("verified") is not True or not his:
            out.append(str(row.get("sha") or "")[:7])
    return out


def _json_pages(text: str) -> list | None:
    """The JSON lists `gh --paginate --jq` printed, one per page, joined; None when one isn't a list."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            page = json.loads(line)
        except ValueError:
            return None
        if not isinstance(page, list):
            return None
        out += page
    return out


async def pr_diff(ref: Ref) -> str:
    """Step brief's read (tier 0): `gh pr diff <n> --repo <owner/repo>`, cut at DIFF_MOST characters."""
    text = await run_gh(["pr", "diff", str(ref.number), "--repo", ref.repo_path])
    if len(text) > DIFF_MOST:
        return text[:DIFF_MOST] + "\n[the rest of the diff is cut]"
    return text


async def root_files(ref: Ref) -> list[str]:
    """The names at the top of the repo (tier 0), for proposing a test command: `gh api repos/<owner/repo>/contents
    --jq .[].name`."""
    text = await run_gh(["api", f"repos/{ref.repo_path}/contents", "--jq", ".[].name"])
    return [line.strip() for line in text.splitlines() if line.strip()]


async def clone(ref: Ref, folder: str, checkout: bool = True) -> None:
    """A copy of the repo in folder (inside a test job's own folder), through gh, signed in as the user. checkout
    False: no files written yet (nothing of his git settings runs on them; odie.loops.pr_test checks out safely)."""
    extra = ["--quiet"]
    if not checkout:
        extra.append("--no-checkout")
    await run_gh(["repo", "clone", ref.repo_path, folder, "--", *extra], seconds=CLONE_SECONDS)


async def merge(ref: Ref, sha: str) -> None:
    """Step merge (tier 2, his tap only): `gh pr merge <n> --repo <owner/repo> --squash --match-head-commit <sha>`.
    GitHub refuses when the head is no longer that commit, so only what was tested can merge. A sha that isn't one
    raises ValueError before anything runs."""
    if not SHA_RE.match(sha or ""):
        raise ValueError("not a commit")
    await run_gh(["pr", "merge", str(ref.number), "--repo", ref.repo_path, "--squash", "--match-head-commit", sha])


async def whoami() -> str:
    """The GitHub login gh is signed in as ("" when it can't say)."""
    try:
        return (await run_gh(["api", "user", "--jq", ".login"])).strip()
    except GitHubError:
        return ""


async def issue_facts(ref: Ref) -> dict:
    """Step issue_facts (tier 0): `gh issue view <n> --repo <owner/repo> --json …`, with whether it is assigned to
    the signed-in user."""
    raw = json.loads(await run_gh(["issue", "view", str(ref.number), "--repo", ref.repo_path, "--json", ISSUE_FIELDS]))
    you = await whoami()
    assignees = [_login(a) for a in raw.get("assignees") or []]
    return {"ref": str(ref), "kind": "issue", "title": str(raw.get("title") or "")[:200],
            "state": str(raw.get("state") or "").lower(), "closed_at": raw.get("closedAt"),
            "author": _login(raw.get("author")), "assignees": assignees, "you": you,
            "assigned_to_you": bool(you) and you in assignees,
            "labels": [str(lb.get("name") or "") for lb in raw.get("labels") or [] if isinstance(lb, dict)],
            "url": link(ref, "issue")}


def when(iso: str | None) -> str:
    """A GitHub time on the user's clock: "2026-11-18T15:34:00Z" in India -> "18 Nov 21:04"; nothing -> ""."""
    if not iso:
        return ""
    from zoneinfo import ZoneInfo

    from odie import config
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return at.astimezone(ZoneInfo(config.settings.timezone)).strftime("%-d %b %H:%M")


CHECK_WORDS = {"green": "CI green", "red": "CI failing", "running": "CI running", "none": "no CI"}


def headline(facts: dict) -> str:
    """The card's facts line, written by code: "Open · CI green · 3 files, +41 −9"; "Draft · CI running · …";
    "Merged 18 Nov 21:04"; "Closed 18 Nov 09:00"; an issue: "Open issue · assigned to you"."""
    state = facts.get("state")
    if state == "merged":
        return f"Merged {when(facts.get('merged_at'))}".strip()
    if state == "closed":
        return f"Closed {when(facts.get('closed_at'))}".strip()
    if facts.get("kind") == "issue":
        assigned = "not assigned to you"
        if facts.get("assigned_to_you"):
            assigned = "assigned to you"
        return f"Open issue · {assigned}"
    status = "Open"
    if facts.get("draft"):
        status = "Draft"
    size = size_words(facts.get("files", 0), facts.get("additions", 0), facts.get("deletions", 0))
    return f"{status} · {ci_words(facts)} · {size}"


def ci_words(facts: dict) -> str:
    """CI in two words for the card: green -> "CI green"; red -> "CI failing"; none -> "no CI"."""
    return CHECK_WORDS.get(facts.get("checks", "none"), "no CI")


def size_words(files: int, additions: int, deletions: int) -> str:
    """A pull request's size: (1, 180, 0) -> "1 file, +180 −0"; (3, 41, 9) -> "3 files, +41 −9"."""
    noun = "files"
    if files == 1:
        noun = "file"
    return f"{files} {noun}, +{additions} −{deletions}"


def evidence(facts: dict) -> str:
    """Why a loop may close, from the facts alone: merged -> "merged 18 Nov 21:04"; closed -> "closed 18 Nov
    09:00"; still open -> "" (no evidence to close on)."""
    if facts.get("state") == "merged":
        return f"merged {when(facts.get('merged_at'))}".strip()
    if facts.get("state") == "closed":
        return f"closed {when(facts.get('closed_at'))}".strip()
    return ""
