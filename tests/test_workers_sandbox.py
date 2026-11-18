"""The default-deny sandbox (second security review, 19 Nov 2026): nothing it starts runs outside it (LaunchServices),
nothing under the home is written or read but the job's folder and the folders the owner named, nothing on this
computer is reachable over the network, nothing it starts outlives a command, and Odie's own file tools never follow a
link. Every secret here is a stand-in under tmp_path; the probe app only touches a marker file in tmp_path."""
from __future__ import annotations

import asyncio
import http.server
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from odie.workers import sandbox, shell

pytestmark = pytest.mark.skipif(not sandbox.available(), reason="no sandbox-exec on this computer")


@pytest.fixture
def job(tmp_path):
    folder = tmp_path / "jobs" / "j1"
    folder.mkdir(parents=True)
    return folder


def run(argv, cwd, timeout=60, env=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def sh(job, script, network=sandbox.NONE, read_dirs=(), home=None):
    argv = sandbox.command(["/bin/sh", "-c", script], job, read_dirs=read_dirs, network=network, home=home)
    return run(argv, job, env=sandbox.env(job))


# ── C1: nothing it starts runs outside it ────────────────────────────────────

def probe_app(job: Path, marker: Path) -> None:
    app = job / "P.app" / "Contents"
    (app / "MacOS").mkdir(parents=True)
    (app / "MacOS" / "P").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (app / "MacOS" / "P").chmod(0o755)
    (app / "Info.plist").write_text('<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
                                    "<key>CFBundleExecutable</key><string>P</string><key>CFBundleIdentifier</key>"
                                    "<string>example.odie.probe</string></dict></plist>")


@pytest.mark.parametrize("network", [sandbox.NONE, sandbox.INTERNET])
def test_open_of_an_app_it_made_runs_nothing_outside(job, tmp_path, network):
    marker = tmp_path / "ESCAPED"
    probe_app(job, marker)
    done = sh(job, "open -g -j P.app; echo open=$?; cp /usr/bin/open ./o 2>/dev/null; ./o -g -j P.app; echo copied=$?; "
                   "osascript -e 1; echo osa=$?", network=network)
    time.sleep(2)
    assert not marker.exists(), done.stdout + done.stderr
    assert "open=0" not in done.stdout and "copied=0" not in done.stdout and "osa=0" not in done.stdout


# ── C2: nothing under the home is written ────────────────────────────────────

def test_no_cache_or_toolchain_under_the_home_is_writable(job, tmp_path):
    home = tmp_path / "home"
    places = [home / ".local/share/uv/python/cpython-3.12/lib", home / ".cache/uv", home / ".npm/_npx",
              home / "Library/Caches/pip"]
    for place in places:
        place.mkdir(parents=True)
    script = "; ".join(f"echo x > '{p}/planted.py'" for p in places)
    sh(job, script, home=home)
    assert [p for p in places if (p / "planted.py").exists()] == []
    assert sh(job, "echo ok > mine.txt && cat mine.txt", home=home).stdout.strip() == "ok"


# ── C3: nothing under the home is read but what the owner named ──────────────

def test_secrets_tokens_and_documents_stay_unread_and_a_named_folder_is_readable(job, tmp_path):
    home = tmp_path / "home"
    stand_ins = {"Library/Application Support/Odie/secrets.json": '{"device": "stand-in"}',
                 ".config/mail-app/credentials.json": "stand-in", ".claude/.credentials.json": "stand-in",
                 "work/proj/.env": "stand-in", "Documents/client.txt": "stand-in"}
    for name, text in stand_ins.items():
        (home / name).parent.mkdir(parents=True, exist_ok=True)
        (home / name).write_text(text)
    named = home / "work" / "app"
    named.mkdir(parents=True)
    (named / "README.md").write_text("the app\n")
    script = "; ".join(f"cat '{home / n}'" for n in stand_ins) + f"; ls '{home}'; cat '{named}/README.md'"
    done = sh(job, script, read_dirs=[str(named)], home=home)
    assert "stand-in" not in done.stdout and "Documents" not in done.stdout
    assert "the app" in done.stdout


def test_nothing_on_this_computer_is_reachable(job, tmp_path):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sock_path = f"/tmp/odie-t{os.getpid()}.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(sock_path)
    listener.listen(1)
    code = (f"import socket\nfor kind, where in (('tcp', ('127.0.0.1', {port})), ('unix', '{sock_path}')):\n"
            "    family = socket.AF_INET if kind == 'tcp' else socket.AF_UNIX\n"
            "    s = socket.socket(family)\n"
            "    try:\n        s.connect(where); print(kind, 'CONNECTED')\n"
            "    except Exception as e:\n        print(kind, type(e).__name__)\n")
    (job / "probe.py").write_text(code)
    try:
        for network in (sandbox.NONE, sandbox.INTERNET):
            done = run(sandbox.command([sys.executable, "probe.py"], job, network=network), job)
            assert "CONNECTED" not in done.stdout, (network, done.stdout, done.stderr)
    finally:
        server.shutdown()
        listener.close()
        os.unlink(sock_path)


# ── I5: nothing it starts outlives a command ─────────────────────────────────

async def test_a_child_that_left_its_group_and_its_folder_is_killed(job):
    # fork, setsid, ignore SIGHUP, let go of the command's output, leave the folder, run under another name
    (job / "s.py").write_text("import os, signal, sys\nif os.fork():\n    sys.exit(0)\nos.setsid()\n"
                              "signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
                              "fd = os.open('/dev/null', os.O_RDWR)\nfor n in (0, 1, 2):\n    os.dup2(fd, n)\n"
                              "os.chdir('/')\nos.execv('/bin/sleep', ['/bin/sleep', '47.25'])\n")
    tool = shell.make_worker_shell(None, SimpleNamespace(id="job-sweep", folder=job, taint="", read_dirs=[]))
    started = time.monotonic()
    await tool.func("env -i /usr/bin/python3 s.py; echo launched")
    assert time.monotonic() - started < 15  # the command returned at once: the child let go of its output
    await asyncio.sleep(0.5)
    found = subprocess.run(["pgrep", "-x", "sleep"], capture_output=True, text=True).stdout.split()
    alive = [pid for pid in found if "47.25" in subprocess.run(["ps", "-o", "args=", "-p", pid],
                                                               capture_output=True, text=True).stdout]
    assert alive == []


# ── C4: Odie's own file tools never follow a link ────────────────────────────

async def test_read_file_and_write_file_refuse_links(job, tmp_path):
    from odie.workers.files import make_job_file_tools
    secret = tmp_path / "secret.env"
    secret.write_text("STAND_IN_SECRET\n")
    outside = tmp_path / "OUTSIDE_TARGET"
    (job / "swap.txt").symlink_to(secret)
    (job / "w.txt").symlink_to(outside)
    (job / "sub").symlink_to(tmp_path)
    write_file, read_file = make_job_file_tools(job)
    assert "error" in await read_file.func("swap.txt")
    assert "error" in await write_file.func("w.txt", "PLANTED")
    assert "error" in await write_file.func("sub/x.txt", "PLANTED")
    assert not outside.exists() and not (tmp_path / "x.txt").exists()
    assert (await write_file.func("real/notes.md", "hi"))["bytes"] == 2
    assert (await read_file.func("real/notes.md"))["text"] == "hi"


def test_a_job_folder_inside_a_denied_tree_is_still_its_own(tmp_path):
    home = tmp_path / "home"
    job = home / ".odie" / "data" / "workspace" / "jobs" / "j2"
    job.mkdir(parents=True)
    (home / ".odie" / ".env").write_text("STAND_IN\n")
    done = sh(job, f"cat '{home}/.odie/.env'; echo mine > a.txt; cat a.txt", home=home)
    assert "STAND_IN" not in done.stdout and "mine" in done.stdout


async def test_recovery_after_a_crash_kills_what_a_cut_off_job_left_running(job, tmp_path, isolated_settings):
    from odie.store.db import Store
    from odie.workers import router
    from odie.workers import store as jobs
    from tests.test_workers import Chat
    store = Store(tmp_path / "r.db")
    store.init_schema()
    router.setup(store, Chat())
    row = jobs.create(store, "task", "Crashed", "x", "chat-2026-11-19", job, 60)
    jobs.started(store, row)
    (job / "d.py").write_text("import os, sys\nif os.fork():\n    sys.exit(0)\nos.setsid()\n"
                              "fd = os.open('/dev/null', os.O_RDWR)\nfor n in (0, 1, 2):\n    os.dup2(fd, n)\n"
                              "os.execv('/bin/sleep', ['/bin/sleep', '48.25'])\n")
    subprocess.run(sandbox.command(["/usr/bin/python3", "d.py"], job), cwd=job, env=sandbox.env(job), timeout=30)
    time.sleep(0.3)  # Odie "crashed" here: nothing of its own remembers the process
    assert await router.recover() == [f"{row.id}: cut off by the restart"]
    time.sleep(0.3)
    found = subprocess.run(["pgrep", "-x", "sleep"], capture_output=True, text=True).stdout.split()
    assert [p for p in found if "48.25" in subprocess.run(["ps", "-o", "args=", "-p", p], capture_output=True,
                                                            text=True).stdout] == []
