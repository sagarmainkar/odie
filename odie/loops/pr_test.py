"""test_pr's run (proactive design §7 step 5): a pull request's tests, run BY CODE in one of Odie's own Worker slots
(odie.workers.router: 2 at once, 8 a day), never by a model with a shell.

  1. clone the repo into the job's own folder through gh (signed in as the user);
  2. fetch the pull request's head and check out exactly the commit the rail looked at (refused if it differs);
  3. run the approved command (one of odie.loops.recipes.TABLE's, checked again here) in the clone, inside the
     default-deny sandbox (odie.workers.sandbox): it reads only the system, the toolchains and the job's own folder
     (nothing of the user's home: no keys, no tokens, no Odie, no documents), writes only the job's folder (HOME, temp
     and every package cache are inside it, so packages download afresh each time), can't start anything outside the
     sandbox (no LaunchServices, no AppleEvents), reaches the internet but nothing on this computer (no localhost, no
     unix sockets), and its environment carries no token, key or SSH agent. Within TEST_SECONDS; whatever it leaves
     running, in its process group or not, is killed when it ends (odie.workers.shell.sweep);
  4. record the exit code, the counts read from the output and the output's tail on the loop: evidence, so "tests
     pass" is a fact, not a claim. The loop gets news and stage 4 looks at it again (the brief, then the card).
The clone is removed afterwards; the whole output is kept in Odie's own record of the job (beside its folder, where no
sandbox can write), opened so that no link a test planted is ever followed. Odie's own git commands in the clone run
with hooks and the file-system monitor switched off, before any of the pull request's code runs."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from odie import config
from odie.loops import github, ledger
from odie.workers import store as jobs

log = logging.getLogger("odie.loops")

TEST_SECONDS = 30 * 60  # the test itself; with the clone it stays inside a Worker's 45 minutes
GIT_SECONDS = 120
TAIL = 4000  # characters of output kept as evidence and shown under "Show failures"
OUTPUT_MOST = 2_000_000  # characters of output read at all; the rest is dropped (the tail is what counts)
KEPT_ENV = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SHELL", "TERM")
RESULT_KEY = "loops.test:{loop_id}"
PASSED = re.compile(r"\b(\d+) passed\b")
FAILED = re.compile(r"\b(\d+) failed\b")


class PrTestError(Exception):
    """The test couldn't be set up (the clone, the commit): said in plain words."""


def clean_env() -> dict[str, str]:
    """The environment of the git commands that set the test up (code's own, never the pull request's): the user's
    home (git's own settings and sign-in), name, language and temp folder, a fixed PATH, CI=1, and nothing else."""
    from odie.agent.tools.shell import SHELL_PATH
    env = {name: os.environ[name] for name in KEPT_ENV if name in os.environ}
    env["PATH"] = SHELL_PATH
    env["CI"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def counts(output: str) -> tuple[int, int] | None:
    """(passed, failed) from the last counts a test runner printed, or None when it printed none:
      "412 passed, 3 skipped in 9.1s" -> (412, 0);  "2 failed, 410 passed" -> (410, 2);
      "Tests: 1 failed, 41 passed, 42 total" -> (41, 1);  "test result: ok. 17 passed; 0 failed" -> (17, 0);
      "all good" -> None"""
    passed = PASSED.findall(output)
    failed = FAILED.findall(output)
    if not passed and not failed:
        return None
    passed_count = 0
    if passed:
        passed_count = int(passed[-1])
    failed_count = 0
    if failed:
        failed_count = int(failed[-1])
    return passed_count, failed_count


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def run_command(argv: list[str], cwd: Path, seconds: float, env: dict | None = None) -> tuple[int | None, str]:
    """Runs argv in cwd (in its own process group) with this environment (clean_env when none); returns (exit code,
    output). Over `seconds` -> the group is stopped and the exit code is None. Whatever it left running is stopped
    when it ends, and when its job is stopped."""
    if env is None:
        env = clean_env()
    proc = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                start_new_session=True)
    chunks: list[bytes] = []
    size = 0

    async def read() -> None:
        nonlocal size
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            size += len(chunk)
            chunks.append(chunk)
            while size > OUTPUT_MOST and len(chunks) > 1:
                size -= len(chunks.pop(0))
        await proc.wait()
    try:
        await asyncio.wait_for(read(), seconds)
    except TimeoutError:
        _kill(proc)
        await proc.wait()
        return None, b"".join(chunks).decode(errors="replace")
    except asyncio.CancelledError:
        _kill(proc)  # the job was stopped: the tests stop with it, process group and all
        raise
    finally:
        _kill(proc)  # a server or watcher the tests started in the background stops too
    return proc.returncode, b"".join(chunks).decode(errors="replace")


async def run_test(command: str, repo: Path, folder: Path) -> tuple[int | None, str]:
    """The approved command in the clone, inside the job's sandbox (internet, never this computer), with HOME, temp
    and caches inside the job's folder; afterwards every process left in its sandbox is killed."""
    from odie.workers import sandbox, shell
    argv = sandbox.command(["/bin/sh", "-c", command], folder, network=sandbox.INTERNET)
    try:
        return await run_command(argv, repo, TEST_SECONDS, env=test_env(folder))
    finally:
        shell.sweep(folder)


def test_env(folder: Path) -> dict[str, str]:
    """The sandbox's environment, with the user's uv-managed Pythons put on PATH: uv uses them as they are (they are
    readable, never writable) instead of downloading one into each job."""
    from odie.workers import sandbox
    env = sandbox.env(folder)
    pythons = sorted(str(p) for p in (Path.home() / ".local/share/uv/python").glob("cpython-*/bin") if p.is_dir())
    if pythons:
        env["PATH"] = ":".join([env["PATH"], *pythons])
    return env


def keep_output(folder: Path, run: int, output: str) -> Path:
    """Writes the test's whole output to output-<run>.log in Odie's record of the job (beside the job's folder, where
    no sandbox writes), creating it fresh and never following a link (O_CREAT | O_EXCL | O_NOFOLLOW)."""
    from odie.workers.shell import records_of
    records = records_of(folder)
    records.mkdir(parents=True, exist_ok=True)
    path = records / f"output-{run}.log"
    if path.is_symlink() or path.exists():
        path.unlink()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(output)
    return path


GIT_SAFE = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "filter.lfs.smudge=",
            "-c", "filter.lfs.process=", "-c", "filter.lfs.required=false")


def git_env() -> dict[str, str]:
    """Odie's own git, outside the sandbox, reads none of his git settings (no filters, LFS or helpers from his global
    or system config run on the pull request's files): GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1."""
    return {**clean_env(), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def credential_args() -> tuple[str, ...]:
    """gh as git's only credential helper (his own settings are off), so a private repo can still be fetched."""
    gh = github.gh_path()
    if not gh:
        return ()
    return ("-c", "credential.helper=", "-c", f"credential.helper=!{gh} auth git-credential")


async def git(cwd: Path, *args: str) -> str:
    """Odie's own git command in the clone: hooks, the file-system monitor, LFS and every setting of his are off,
    so nothing in the repository runs (the pull request's code runs only in the sandbox)."""
    code, out = await run_command(["git", *GIT_SAFE, *credential_args(), *args], cwd, GIT_SECONDS, env=git_env())
    if code != 0:
        raise PrTestError(f"git {args[0]} failed: {out.strip()[:200]}")
    return out.strip()


async def checkout(ref: github.Ref, sha: str, folder: Path) -> Path:
    """The repo cloned into folder/repo with the pull request's head commit checked out; a different commit there
    raises PrTestError (the rail looked at that one)."""
    repo = folder / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    try:
        await github.clone(ref, str(repo), checkout=False)
    except github.GitHubError as e:
        raise PrTestError(f"the clone failed: {e}") from e
    await git(repo, "fetch", "-q", "origin", f"pull/{ref.number}/head")
    await git(repo, "checkout", "-q", "--detach", sha)
    head = await git(repo, "rev-parse", "HEAD")
    if head != sha:
        raise PrTestError(f"the checkout is at {head[:7]}, not {sha[:7]}")
    return repo


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.settings.timezone))


def fact_of(result: dict) -> str:
    """The evidence line: "Tested abc1234 with `uv run pytest -q`: exit 0, 412 passed"; with failures
    "…: exit 1, 410 passed, 2 failed"; over time "Testing abc1234 took longer than 30 minutes"; a setup failure
    "The test of abc1234 couldn't run: the clone failed: …"."""
    short = result["sha"][:7]
    if result.get("error"):
        return f"The test of {short} couldn't run: {result['error']}"
    if result["exit"] is None:
        return f"Testing {short} took longer than {TEST_SECONDS // 60} minutes"
    line = f"Tested {short} with `{result['command']}`: exit {result['exit']}"
    if result["passed"] is not None:
        line += f", {result['passed']} passed"
    if result["failed"]:
        line += f", {result['failed']} failed"
    return line


def record(store, loop_id: int, result: dict) -> None:
    """The test's result on its loop: kept whole for the brief and the card, one evidence line, and news, so stage 4
    looks at the loop again."""
    store.set_setting(RESULT_KEY.format(loop_id=loop_id), result)
    loop = ledger.get(store, loop_id)
    if loop is None:
        return
    now = now_local()
    ledger.add_event(store, loop_id, now, "test", result["sha"][:7], fact_of(result))
    if loop["state"] in ledger.OPEN:
        ledger.update(store, loop_id, now, has_news=1, next_check_at=now.isoformat(timespec="seconds"))


def result_for(store, loop_id: int) -> dict | None:
    """The last test of this loop's pull request, or None when it was never tested."""
    return store.get_setting(RESULT_KEY.format(loop_id=loop_id))


def mark_carded(store, loop_id: int, checks: str, title: str) -> None:
    """The tested card is up for this result, with CI as it was then and the card's title: Merge may be offered."""
    result = result_for(store, loop_id)
    if result is None:
        return
    store.set_setting(RESULT_KEY.format(loop_id=loop_id), {**result, "carded": True, "checks": checks, "title": title})


def uncard(store, loop_id: int) -> None:
    """New commits since the test: its card may no longer offer Merge."""
    result = result_for(store, loop_id)
    if result is None:
        return
    store.set_setting(RESULT_KEY.format(loop_id=loop_id), {**result, "carded": False})


def running_for(store, loop_id: int) -> bool:
    """Whether a test of this loop is queued or running now."""
    row = store.one("select 1 from jobs where loop_id=? and kind='pr_test' and status in ('queued','running') "
                    "and version >= 2", (loop_id,))
    return row is not None


def start(store, loop: dict, ref: github.Ref, sha: str, command: str):
    """Starts the test in one of Odie's own slots; None when today's 8 are used. The spec is the job's brief."""
    from odie.workers import router
    spec = {"ref": str(ref), "sha": sha, "command": command}
    return router.start(f"Testing {ref.repo_path} #{ref.number}", json.dumps(spec), None,
                        personality=loop["personality"], kind="pr_test", started_by="odie", loop_id=loop["id"])


def _spec(row_brief: str) -> dict:
    try:
        spec = json.loads(row_brief)
    except ValueError:
        return {}
    if not isinstance(spec, dict):
        return {}
    return spec


async def run_job(job, store) -> str:
    """The test job's run (the router calls it in the slot): set up, run, record. Returns "done" (it ran, whatever
    the tests said) or "failed" (it couldn't run, or ran out of time)."""
    jobs.started(store, job)
    spec = _spec(job.brief)
    ref = github.parse(spec.get("ref", ""))
    sha = str(spec.get("sha") or "")
    command = str(spec.get("command") or "")
    result = {"sha": sha, "command": command, "exit": None, "passed": None, "failed": 0, "ok": False, "tail": "",
              "at": now_local().isoformat(timespec="seconds"), "job_id": job.id, "error": ""}
    try:
        from odie.loops import recipes
        from odie.workers import sandbox
        if ref is None or not github.SHA_RE.match(sha) or not recipes.runnable(command):
            raise PrTestError("the test's spec is broken")
        if not sandbox.available():
            raise PrTestError("this computer has no sandbox to run tests in")
        repo = await checkout(ref, sha, job.folder)
        code, output = await run_test(command, repo, job.folder)
        keep_output(job.folder, job.runs, output)
        found = counts(output)
        result.update(exit=code, tail=output[-TAIL:], ok=code == 0)
        if found is not None:
            result.update(passed=found[0], failed=found[1])
    except (PrTestError, OSError) as e:
        result["error"] = str(e)[:300]
    finally:
        shutil.rmtree(job.folder / "repo", ignore_errors=True)
    if job.loop_id is not None:
        record(store, job.loop_id, result)
    line = fact_of(result)
    if result["error"] or result["exit"] is None:
        jobs.ended(store, job.id, "failed", error=line)
        return "failed"
    jobs.ended(store, job.id, "done", outcome="ready", report=line)
    return "done"


def cut_off(store, row: dict, why: str) -> None:
    """A test the watchdog or a restart ended: its loop hears it couldn't finish (and may test again later)."""
    spec = _spec(row["brief"])
    if row.get("loop_id") is None:
        return
    result = {"sha": str(spec.get("sha") or "?" * 7), "command": str(spec.get("command") or ""), "exit": None,
              "passed": None, "failed": 0, "ok": False, "tail": "", "at": now_local().isoformat(timespec="seconds"),
              "job_id": row["id"], "error": why}
    record(store, row["loop_id"], result)
