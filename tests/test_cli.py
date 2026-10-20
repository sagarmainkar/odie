"""The odie command (odie/cli.py) against a fake world: launchctl, git, uv, npm, lsof, tailscale and HTTP all go through
a fake runner, and every path is a temporary one (each test checks it isn't the real home, service or command)."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from odie import cli

ROOT = Path(__file__).resolve().parent.parent
REAL_HOME = Path.home() / ".odie"
REAL_LABEL = "dev.odie.server"
REAL_COMMAND = Path.home() / ".local" / "bin" / "odie"
REAL_AGENTS = Path.home() / "Library" / "LaunchAgents"
OLD = "a" * 40
NEW = "b" * 40


class World:
    """A pretend Mac: a live copy checked out at `head`, origin/main at `origin`, the service loaded or not, and which
    commits build and which come up healthy. The fake runner below plays launchctl, git, uv, npm and HTTP against it."""

    def __init__(self, inst: cli.Install):
        self.inst = inst
        self.head = OLD
        self.origin = OLD
        self.loaded = False
        self.running = ""          # the commit the service process runs
        self.broken_builds: set[str] = set()
        self.unhealthy: set[str] = set()
        self.dirty = ""
        self.fetch_code = 0
        self.tags: list[str] = []  # the release tags origin has (an install that follows releases reads them)
        self.someone_else_on_port = False
        self.health_extra: dict = {}
        self.tailscale_serve = ""
        self.events: list[str] = []
        self.calls: list[list[str]] = []
        self.slept = 0.0

    # the runner's three methods
    def run(self, args, cwd=None, log=None, timeout=900):
        args = [str(a) for a in args]
        self.calls.append(args)
        if log is not None:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                f.write("$ " + " ".join(args) + "\n")
        return self._answer(args, cwd)

    def get(self, url, timeout=3):
        if not self.healthy_now():
            return None
        if url.endswith("/api/health"):
            return 200, json.dumps({"status": "ok", **self.health_extra})
        return 200, "<html>Odie</html>"

    def sleep(self, seconds):
        self.slept += seconds

    # the world's rules
    def healthy_now(self) -> bool:
        return self.loaded and self.running not in self.unhealthy

    def _answer(self, args, cwd):
        tool = args[0]
        if tool == "git":
            return self._git(args[3:])
        if tool in ("uv", "npm"):
            self.events.append(f"build {' '.join(args[:3])} @{self.head[:1]}")
            if args[:3] == ["npm", "run", "build"] and self.head in self.broken_builds:
                return cli.Ran(1, "build error")
            return cli.Ran(0, "")
        if tool == "launchctl":
            return self._launchctl(args[1:])
        if tool == "lsof":
            if self.someone_else_on_port:
                return cli.Ran(0, "999\n")
            if self.loaded:
                return cli.Ran(0, "123\n")
            return cli.Ran(1, "")
        if tool == "tailscale":
            if args[1:3] == ["serve", "status"]:
                return cli.Ran(0, self.tailscale_serve)
            return cli.Ran(0, json.dumps({"Self": {"DNSName": "mini.tail1234.ts.net."}}))
        if tool == "ps":
            return cli.Ran(0, "Sat Oct 11 09:12:03 2026\n")
        if tool == "open":
            self.events.append(f"open {args[1]}")
            return cli.Ran(0, "")
        raise AssertionError(f"unexpected command {args}")

    def _git(self, rest):
        if rest == ["rev-parse", "HEAD"]:
            return cli.Ran(0, self.head + "\n")
        if rest == ["status", "--porcelain"]:
            return cli.Ran(0, self.dirty)
        if rest[:1] == ["fetch"]:
            return cli.Ran(self.fetch_code, "")
        if rest[:2] == ["tag", "-l"]:
            return cli.Ran(0, "\n".join(self.tags) + "\n")
        if rest[:1] == ["rev-parse"]:
            return cli.Ran(0, self.origin + "\n")
        if rest[:1] == ["checkout"]:
            self.head = rest[-1]
            self.events.append(f"checkout @{self.head[:1]}")
            return cli.Ran(0, "")
        if rest[:1] == ["log"]:
            return cli.Ran(0, f"{self.head[:7]}\tMerge pull request #41 from x/y\t2026-10-11\n")
        raise AssertionError(f"unexpected git {rest}")

    def _launchctl(self, rest):
        verb = rest[0]
        if verb == "print":
            if not self.loaded:
                return cli.Ran(113, "Could not find service")
            return cli.Ran(0, "dev.odie.x = {\n\tstate = running\n\truns = 3\n\tpid = 123\n\t\tpid = 7\n}\n")
        if verb == "bootstrap":
            self.loaded = True
            self.running = self.head
            self.events.append("bootstrap")
            return cli.Ran(0, "")
        if verb == "bootout":
            self.loaded = False
            self.running = ""
            self.events.append("bootout")
            return cli.Ran(0, "")
        if verb == "kickstart":
            self.running = self.head
            self.events.append(f"kickstart @{self.head[:1]}")
            return cli.Ran(0, "")
        raise AssertionError(f"unexpected launchctl {rest}")


@pytest.fixture
def env(tmp_path):
    values = {
        "ODIE_HOME": str(tmp_path / "home"),
        "ODIE_SERVICE_LABEL": "dev.odie.unittest",
        "ODIE_PORT": "8999",
        "ODIE_BIN_DIR": str(tmp_path / "bin"),
        "ODIE_LAUNCH_AGENTS": str(tmp_path / "agents"),
        "ODIE_BRANCH": "main",
    }
    return values


@pytest.fixture
def inst(env):
    i = cli.install_from(env)
    # never the real ones
    assert i.home != REAL_HOME and REAL_HOME not in i.home.parents
    assert i.label != REAL_LABEL
    assert i.command != REAL_COMMAND
    assert i.agents_dir != REAL_AGENTS
    assert i.port not in (8000, 8771)
    return i


@pytest.fixture
def world(inst):
    (inst.app / ".git").mkdir(parents=True)
    return World(inst)


# ── paths ──

def test_paths_come_from_the_environment(inst, tmp_path):
    assert inst.app == tmp_path / "home" / "app"
    assert inst.plist == tmp_path / "agents" / "dev.odie.unittest.plist"
    assert inst.command == tmp_path / "bin" / "odie"
    assert inst.server_log == tmp_path / "home" / "logs" / "server.log"
    assert inst.voice_port == 8999 + 771
    assert inst.service.endswith("/dev.odie.unittest")


def test_defaults_are_the_real_install():
    i = cli.install_from({})
    assert i.home == REAL_HOME and i.label == REAL_LABEL and i.port == 8000 and i.voice_port == 8771
    assert i.command == REAL_COMMAND and i.agents_dir == REAL_AGENTS and i.branch == "releases" and i.voice


def test_voice_wanted():
    assert cli.voice_wanted("off") is False
    assert cli.voice_wanted("0") is False
    assert cli.voice_wanted("") is True
    assert cli.voice_wanted("on") is True


def test_tool_path_puts_homebrew_first():
    assert cli.tool_path("/usr/bin:/opt/homebrew/bin").split(":") == ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]


# ── start / stop / restart ──

def test_the_service_file_runs_odie_serve_from_the_live_copy(inst):
    plist = cli.plist_contents(inst, {"ODIE_VOICE": "off", "ODIE_PAIRING": "off", "SECRET_KEY": "x"})
    assert plist["Label"] == "dev.odie.unittest"
    assert plist["ProgramArguments"] == [str(inst.python), "-P", "-m", "odie.cli", "serve"]
    assert plist["WorkingDirectory"] == str(inst.app)
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert plist["StandardOutPath"] == plist["StandardErrorPath"] == str(inst.server_log)
    env = plist["EnvironmentVariables"]
    assert env["ODIE_HOME"] == str(inst.home) and env["ODIE_PORT"] == "8999"
    assert env["ODIE_BRANCH"] == "main"  # the app's update check runs in the service: it must follow the same thing
    assert env["ODIE_VOICE"] == "off" and env["ODIE_PAIRING"] == "off"
    assert "SECRET_KEY" not in env
    assert env["PATH"].startswith("/opt/homebrew/bin")


def test_start_needs_an_install(inst, capsys):
    w = World(inst)
    assert cli.cmd_start(inst, w, {}) == 1
    assert "scripts/install.sh" in capsys.readouterr().out
    assert w.events == []


def test_start_writes_the_service_and_waits_until_healthy(inst, world, capsys):
    assert cli.cmd_start(inst, world, {"ODIE_VOICE": "off"}) == 0
    assert world.events == ["bootstrap"]
    with inst.plist.open("rb") as f:
        assert plistlib.load(f)["EnvironmentVariables"]["ODIE_VOICE"] == "off"
    assert inst.logs.is_dir()
    assert "Odie is running: http://localhost:8999" in capsys.readouterr().out


def test_start_says_so_when_it_does_not_come_up(inst, world, capsys):
    world.unhealthy.add(OLD)
    assert cli.cmd_start(inst, world, {}) == 1
    assert "odie logs -e" in capsys.readouterr().out


def test_start_refuses_when_someone_else_has_the_port(inst, world, capsys):
    world.someone_else_on_port = True
    assert cli.cmd_start(inst, world, {}) == 1
    assert "Something else is answering on port 8999" in capsys.readouterr().out
    assert not inst.plist.exists()
    assert "bootstrap" not in world.events


def test_start_when_already_running(inst, world, capsys):
    world.loaded = True
    assert cli.cmd_start(inst, world, {}) == 0
    assert "already running" in capsys.readouterr().out
    assert world.events == []


TAILSCALE_HERE = "https://mini.tail1234.ts.net (tailnet only)\n|-- / proxy http://127.0.0.1:8999\n"


def test_start_shows_the_phone_address(inst, world, capsys):
    world.tailscale_serve = TAILSCALE_HERE
    assert cli.cmd_start(inst, world, {}) == 0
    out = capsys.readouterr().out
    assert "Odie is running: http://localhost:8999" in out
    assert "phone:  https://mini.tail1234.ts.net" in out


def test_start_without_a_phone_address_shows_only_this_mac(inst, world, capsys):
    assert cli.cmd_start(inst, world, {}) == 0
    assert "phone:" not in capsys.readouterr().out


def test_a_first_start_says_how_to_pair_from_elsewhere(inst, world, capsys):
    assert cli.cmd_start(inst, world, {}) == 0  # no database yet: nothing is paired
    assert cli.PAIRING_HINT in capsys.readouterr().out
    assert "odie pair" in cli.PAIRING_HINT


def test_no_pairing_hint_once_a_device_is_paired(inst, world, capsys):
    store = odie_database(inst)
    pair_a_device(store)
    store.close()
    assert cli.cmd_start(inst, world, {}) == 0
    assert cli.PAIRING_HINT not in capsys.readouterr().out


def test_no_pairing_hint_when_pairing_is_off(inst, world, capsys):
    assert cli.cmd_start(inst, world, {"ODIE_PAIRING": "off"}) == 0
    assert cli.PAIRING_HINT not in capsys.readouterr().out


def test_stop_unloads_and_removes_the_service_file(inst, world, capsys):
    cli.cmd_start(inst, world, {})
    assert cli.cmd_stop(inst, world) == 0
    assert world.events == ["bootstrap", "bootout"]
    assert not inst.plist.exists()  # so it doesn't start at the next login either
    assert "stays stopped" in capsys.readouterr().out


def test_stop_when_not_running(inst, world, capsys):
    assert cli.cmd_stop(inst, world) == 0
    assert "wasn't running" in capsys.readouterr().out


def test_restart_is_stop_then_start(inst, world):
    cli.cmd_start(inst, world, {})
    assert cli.cmd_restart(inst, world, {}) == 0
    assert world.events == ["bootstrap", "bootout", "bootstrap"]
    assert inst.plist.exists()


def test_restart_when_stopped_just_starts(inst, world, capsys):
    assert cli.cmd_restart(inst, world, {}) == 0
    assert world.events == ["bootstrap"]
    assert "wasn't running" not in capsys.readouterr().out


def test_port_taken_by_someone_else(inst, world):
    assert cli.port_taken_by_someone_else(inst, world) is False   # nothing listening
    world.loaded = True
    assert cli.port_taken_by_someone_else(inst, world) is False   # our service's pid listens
    world.someone_else_on_port = True
    assert cli.port_taken_by_someone_else(inst, world) is True    # pid 999 isn't ours
    world.loaded = False
    assert cli.port_taken_by_someone_else(inst, world) is True


def test_big_logs_are_moved_aside_at_start(inst, world):
    inst.logs.mkdir(parents=True)
    inst.server_log.write_bytes(b"x" * (cli.LOG_ROTATE_BYTES + 1))
    cli.cmd_start(inst, world, {})
    assert (inst.logs / "server.log.1").exists() and not inst.server_log.exists()
    assert cli.log_too_big(12 * 1024 * 1024) is True
    assert cli.log_too_big(3 * 1024 * 1024) is False


# ── status / open ──

def test_status_running(inst, world, capsys):
    world.loaded = True
    world.running = OLD
    world.health_extra = {"provider": "ollama", "model": "glm-5.3-flash:cloud"}
    world.tailscale_serve = "https://mini.tail1234.ts.net (tailnet only)\n|-- / proxy http://127.0.0.1:8999\n"
    assert cli.cmd_status(inst, world, now=datetime(2026, 10, 11, 12, 0)) == 0
    out = capsys.readouterr().out
    assert "Odie is running  ·  version aaaaaaa (Merge #41, 2026-10-11)  ·  healthy" in out
    assert "this Mac:  http://localhost:8999" in out
    assert "phone:     https://mini.tail1234.ts.net" in out
    assert "model:     Ollama · glm-5.3-flash:cloud" in out
    assert "started:   09:12 today  ·  restarts since it was loaded: 2" in out


def test_status_when_pairing_hides_the_model(inst, world, capsys):
    save_model_choice(inst, {"provider": "anthropic", "model": "claude-x"})
    before = tree(inst.home)
    world.loaded = True
    world.running = OLD
    cli.cmd_status(inst, world)
    out = capsys.readouterr().out
    assert "model:     Claude · claude-x" in out  # from the saved settings: health tells only paired devices
    assert tree(inst.home) == before  # the database is only read
    assert "phone:" not in out  # tailscale serve doesn't point here


def test_status_stopped(inst, world, capsys):
    assert cli.cmd_status(inst, world) == 1
    out = capsys.readouterr().out
    assert "Odie is stopped" in out and "odie start" in out


def test_status_running_but_unhealthy(inst, world, capsys):
    world.loaded = True
    world.running = OLD
    world.unhealthy.add(OLD)
    assert cli.cmd_status(inst, world) == 1
    assert "not answering (odie logs -e)" in capsys.readouterr().out


# ── pair ──

def odie_database(inst: cli.Install):
    """The install's database with Odie's real schema, as its first start leaves it (in the temporary home)."""
    from odie.store.db import Store
    assert inst.database.is_relative_to(inst.home) and inst.home != REAL_HOME
    store = Store(inst.database)
    store.init_schema()
    return store


def pair_a_device(store) -> None:
    """A paired device's row, as odie.devices.add_device writes it (without touching any setup-link file)."""
    store.execute("insert into devices(name,key_hash,created_at,last_seen_at) values('Mac, Safari','x',0,0)")


def redeems(inst: cli.Install, code: str) -> bool:
    from odie import devices
    from odie.store.db import Store
    store = Store(inst.database)
    try:
        return devices.redeem_code(store, code)
    finally:
        store.close()


def printed_code(out: str) -> str:
    import re
    match = re.search(r"Pairing code: ([A-Z0-9]{4}-[A-Z0-9]{4})", out)
    assert match, out
    return match.group(1)


def test_pair_prints_a_code_that_odie_accepts_once(env, inst, world, capsys):
    odie_database(inst).close()
    assert cli.main(["pair"], environ=env, runner=world) == 0
    out = capsys.readouterr().out
    code = printed_code(out)
    assert "valid once, for 10 minutes" in out
    assert "this Mac:  http://localhost:8999" in out
    assert "phone:" not in out and "scan" not in out  # tailscale serve doesn't point here
    assert redeems(inst, code) is True
    assert redeems(inst, code) is False  # good once


def test_pair_with_a_phone_address_shows_it_and_a_qr_code(inst, world, capsys):
    odie_database(inst).close()
    world.tailscale_serve = TAILSCALE_HERE
    assert cli.cmd_pair(inst, world, {}) == 0
    out = capsys.readouterr().out
    code = printed_code(out)
    assert "phone:     https://mini.tail1234.ts.net" in out
    qr_lines = cli.terminal_qr(f"https://mini.tail1234.ts.net/#pair={code}")
    assert "\n".join(qr_lines) in out


def test_pair_needs_an_install(inst, capsys):
    assert cli.cmd_pair(inst, World(inst), {}) == 1
    assert "scripts/install.sh" in capsys.readouterr().out
    assert not inst.database.exists()


def test_pair_needs_odie_to_have_started_once(inst, world, capsys):
    assert cli.cmd_pair(inst, world, {}) == 1
    assert "odie start" in capsys.readouterr().out
    assert not inst.database.exists()  # it doesn't make one


def test_pair_when_pairing_is_off_needs_no_code(inst, world, capsys):
    store = odie_database(inst)
    store.set_setting("pairing", {"on": False})
    store.close()
    assert cli.cmd_pair(inst, world, {}) == 0
    out = capsys.readouterr().out
    assert "Pairing is off" in out and "Pairing code" not in out


def test_pairing_asked_for(inst):
    assert cli.pairing_asked_for(inst, {}) is True  # no database yet: a new install
    store = odie_database(inst)
    assert cli.pairing_asked_for(inst, {}) is True  # nothing saved yet
    store.set_setting("pairing", {"on": False})
    assert cli.pairing_asked_for(inst, {}) is False
    assert cli.pairing_asked_for(inst, {"ODIE_PAIRING": "on"}) is True  # the environment wins, as in the server
    store.set_setting("pairing", {"on": True})
    assert cli.pairing_asked_for(inst, {"ODIE_PAIRING": "off"}) is False
    store.close()


def test_paired_device_count(inst):
    assert cli.paired_device_count(inst) == 0  # no database
    store = odie_database(inst)
    assert cli.paired_device_count(inst) == 0
    pair_a_device(store)
    assert cli.paired_device_count(inst) == 1
    store.close()


def test_terminal_qr_draws_every_module():
    """Reads the drawing back, two rows per line, and compares it with the QR code itself."""
    from odie import qr
    text = "https://mini.tail1234.ts.net/#pair=ABCD-EFGH"
    matrix = qr.encode(text)
    size = len(matrix)
    lines = cli.terminal_qr(text, border=2)
    upper = {"█": True, "▀": True, "▄": False, " ": False}
    lower = {"█": True, "▀": False, "▄": True, " ": False}
    read_back = []
    for line in lines:
        assert line.startswith(cli.DARK_ON_LIGHT) and line.endswith(cli.PLAIN)
        chars = line.removeprefix(cli.DARK_ON_LIGHT).removesuffix(cli.PLAIN)
        assert len(chars) == size + 4
        read_back.append([upper[c] for c in chars])
        read_back.append([lower[c] for c in chars])
    expected = [[False] * (size + 4) for _ in range(2)]
    for row in matrix:
        expected.append([False, False, *row, False, False])
    while len(expected) < len(read_back):
        expected.append([False] * (size + 4))
    assert read_back == expected


def test_open(inst, world):
    assert cli.cmd_open(inst, world) == 0
    assert world.events == ["open http://localhost:8999"]


def test_open_right_after_an_install_opens_no_second_tab(inst, world, capsys):
    # The service has just written its setup link and opened it itself: a second tab would sit blank until the first
    # one pairs (20 Oct 2026). Later, with that tab closed, the link is what gets opened, not the plain address.
    import os
    link = inst.home / "setup-link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("http://localhost:8999/#setup=abc")
    assert cli.cmd_open(inst, world) == 0
    assert world.events == [] and "already open" in capsys.readouterr().out
    old = link.stat().st_mtime - cli.SETUP_LINK_JUST_OPENED - 1
    os.utime(link, (old, old))
    assert cli.cmd_open(inst, world) == 0
    assert world.events == ["open http://localhost:8999/#setup=abc"]


def test_short_subject():
    assert cli.short_subject("Merge pull request #41 from someone/schema-cleanup") == "Merge #41"
    assert cli.short_subject("Short one") == "Short one"
    long = "Calendar watch reads whole days for date_from and more"
    assert cli.short_subject(long) == long[:39] + "…"


def test_started_at_another_day(world):
    assert cli.started_at("123", world, datetime(2026, 10, 12, 8, 0)) == "Oct 11, 09:12"


# ── logs ──

LOG = """2026-10-11 09:12:00,100 odie INFO started
INFO:     127.0.0.1:5000 - "GET / HTTP/1.1" 200 OK
2026-10-11 09:12:05,200 odie.turn ERROR turn failed
Traceback (most recent call last):
  File "x.py", line 3, in f
ValueError: bad
Odie: http://localhost:8000  ·  voice worker: port 8771
INFO:     127.0.0.1:5000 - "GET /api/health HTTP/1.1" 200 OK
WARNING:  Invalid HTTP request received.
2026-10-11 09:13:00,300 odie WARNING local voice couldn't start
2026-10-11 09:14:00,400 odie INFO all good
"""


def test_problem_filter_keeps_warnings_errors_and_their_tracebacks():
    problems = cli.ProblemFilter()
    kept = [line for line in LOG.splitlines() if problems.keep(line)]
    assert kept == [
        "2026-10-11 09:12:05,200 odie.turn ERROR turn failed",
        "Traceback (most recent call last):",
        '  File "x.py", line 3, in f',
        "ValueError: bad",
        "WARNING:  Invalid HTTP request received.",
        "2026-10-11 09:13:00,300 odie WARNING local voice couldn't start",
    ]


def test_logs_last_lines(inst, world, capsys):
    inst.logs.mkdir(parents=True)
    inst.server_log.write_text(LOG)
    assert cli.cmd_logs(inst, world, lines=2, errors_only=False, keep_following=False) == 0
    assert capsys.readouterr().out.splitlines() == [
        "2026-10-11 09:13:00,300 odie WARNING local voice couldn't start", "2026-10-11 09:14:00,400 odie INFO all good"]


def test_logs_errors_only(inst, world, capsys):
    inst.logs.mkdir(parents=True)
    inst.server_log.write_text(LOG)
    cli.cmd_logs(inst, world, lines=3, errors_only=True, keep_following=False)
    assert capsys.readouterr().out.splitlines() == [
        "ValueError: bad", "WARNING:  Invalid HTTP request received.",
        "2026-10-11 09:13:00,300 odie WARNING local voice couldn't start"]


def test_logs_follow_prints_new_lines(inst, world, capsys):
    inst.logs.mkdir(parents=True)
    inst.server_log.write_text("old line\n")
    rounds = iter([True, True, False])

    def keep_going():
        going = next(rounds)
        if going:
            with inst.server_log.open("a") as f:
                f.write("new line\n")
        return going

    cli.cmd_logs(inst, world, lines=None, errors_only=False, keep_following=False, keep_going=keep_going)
    assert capsys.readouterr().out.splitlines() == ["old line", "new line", "new line"]


def test_logs_without_a_log(inst, world, capsys):
    assert cli.cmd_logs(inst, world, lines=5, errors_only=False, keep_following=False) == 1
    assert "No log yet" in capsys.readouterr().out


# ── update ──

def running_world(world: World, origin: str = NEW) -> World:
    world.loaded = True
    world.running = world.head
    world.origin = origin
    return world


def test_update_when_already_up_to_date(inst, world, capsys):
    running_world(world, origin=OLD)
    assert cli.cmd_update(inst, world) == 0
    assert "Already up to date: aaaaaaa" in capsys.readouterr().out
    assert world.events == []
    assert not inst.previous_file.exists()


def test_update_moves_to_the_newest_and_remembers_the_previous(inst, world, capsys):
    running_world(world)
    assert cli.cmd_update(inst, world) == 0
    assert world.events == ["checkout @b", "build uv sync --frozen @b", "build uv sync --frozen @b", "build uv sync --frozen @b",
                            "build npm ci @b", "build npm run build @b", "kickstart @b"]  # Odie's, the voice worker's, the embedding service's
    assert world.head == NEW and world.running == NEW
    assert inst.previous_file.read_text().strip() == OLD
    out = capsys.readouterr().out
    assert "Updating aaaaaaa → bbbbbbb" in out and "and healthy" in out
    assert inst.update_log.exists()


def test_update_skips_the_workers_that_are_off(env, world, capsys):
    inst = cli.install_from({**env, "ODIE_VOICE": "off", "ODIE_EMBED": "off"})
    running_world(world)
    assert cli.cmd_update(inst, world) == 0
    assert [e for e in world.events if e.startswith("build")] == [
        "build uv sync --frozen @b", "build npm ci @b", "build npm run build @b"]


def test_update_build_fails_goes_back_and_never_stops_odie(inst, world, capsys):
    running_world(world)
    world.broken_builds.add(NEW)
    assert cli.cmd_update(inst, world) == 1
    assert world.head == OLD and world.running == OLD
    assert world.events[0] == "checkout @b" and "checkout @a" in world.events
    assert world.events[-1] == "build npm run build @a"  # the previous version rebuilt
    assert not any(e.startswith(("kickstart", "bootout", "bootstrap")) for e in world.events)  # never stopped
    out = capsys.readouterr().out
    assert "npm run build failed" in out and "kept running" in out


def test_update_unhealthy_after_restart_rolls_back(inst, world, capsys):
    running_world(world)
    world.unhealthy.add(NEW)
    assert cli.cmd_update(inst, world) == 1
    assert world.head == OLD and world.running == OLD
    assert [e for e in world.events if e.startswith(("checkout", "kickstart"))] == [
        "checkout @b", "kickstart @b", "checkout @a", "kickstart @a"]
    assert "Rolled back to aaaaaaa" in capsys.readouterr().out


def test_update_rollback_also_unhealthy(inst, world, capsys):
    running_world(world)
    world.unhealthy.update({NEW, OLD})
    assert cli.cmd_update(inst, world) == 2
    out = capsys.readouterr().out
    assert "Even aaaaaaa isn't healthy" in out and str(inst.server_log) in out


def test_update_force_rebuilds_the_same_commit(inst, world, capsys):
    running_world(world, origin=OLD)
    inst.home.mkdir(parents=True, exist_ok=True)
    cli.remember_rollback_point(inst, "c" * 40)
    assert cli.cmd_update(inst, world, force=True) == 0
    assert "kickstart @a" in world.events
    assert inst.previous_file.read_text().strip() == "c" * 40  # the last real update's rollback point stays


def test_update_when_odie_is_stopped_only_builds(inst, world, capsys):
    world.origin = NEW
    assert cli.cmd_update(inst, world) == 0
    assert world.head == NEW
    assert not any(e.startswith(("kickstart", "bootstrap")) for e in world.events)
    assert "Odie is stopped" in capsys.readouterr().out


def test_update_follows_the_newest_release(env, world, capsys):
    inst = cli.install_from({**env, "ODIE_BRANCH": "releases"})
    world.tags = ["v0.1.0", "v0.10.0", "v0.2.0", "film-take-3"]
    running_world(world)
    assert cli.cmd_update(inst, world) == 0
    asked = [c for c in world.calls if "rev-parse" in c and "HEAD" not in c]
    assert asked[-1][-1] == "v0.10.0^{commit}"  # by version number, not by text
    assert world.head == NEW


def test_update_with_no_release_yet_changes_nothing(env, world, capsys):
    inst = cli.install_from({**env, "ODIE_BRANCH": "releases"})
    running_world(world)
    assert cli.cmd_update(inst, world) == 1
    assert "There's no release to update to yet." in capsys.readouterr().out
    assert world.head == OLD and world.events == []


def test_update_following_main_asks_for_origin_main(inst, world):
    running_world(world)
    cli.cmd_update(inst, world)
    asked = [c for c in world.calls if "rev-parse" in c and "HEAD" not in c]
    assert asked[-1][-1] == "origin/main^{commit}"


def test_update_cannot_fetch(inst, world, capsys):
    running_world(world)
    world.fetch_code = 128
    assert cli.cmd_update(inst, world) == 1
    assert "Couldn't fetch" in capsys.readouterr().out
    assert world.events == []


def test_update_refuses_a_changed_copy(inst, world, capsys):
    running_world(world)
    world.dirty = " M odie/cli.py\n"
    assert cli.cmd_update(inst, world) == 1
    assert "local changes" in capsys.readouterr().out
    assert world.events == []


def test_rollback_goes_to_the_remembered_commit(inst, world, capsys):
    running_world(world, origin=NEW)
    cli.cmd_update(inst, world)
    world.events.clear()
    assert cli.cmd_update(inst, world, rollback=True) == 0
    assert world.head == OLD and world.running == OLD
    assert world.events[0] == "checkout @a" and world.events[-1] == "kickstart @a"
    assert inst.previous_file.read_text().strip() == NEW  # so the rollback can be undone the same way
    assert "Going back to aaaaaaa" in capsys.readouterr().out


def test_rollback_that_is_unhealthy_returns_to_where_it_was(inst, world, capsys):
    running_world(world, origin=NEW)
    cli.cmd_update(inst, world)
    world.unhealthy.add(OLD)
    assert cli.cmd_update(inst, world, rollback=True) == 1
    assert world.head == NEW and world.running == NEW


def test_rollback_with_nothing_remembered(inst, world, capsys):
    running_world(world)
    assert cli.cmd_update(inst, world, rollback=True) == 1
    assert "No earlier version" in capsys.readouterr().out
    assert world.events == []


# ── doctor ──

def tree(folder: Path) -> dict[str, tuple[int, float]]:
    return {str(p): (p.stat().st_size, p.stat().st_mtime) for p in folder.rglob("*")}


def test_doctor_all_good(inst, world, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli.shutil, "which", lambda tool, path=None: f"/opt/homebrew/bin/{tool}")
    running_world(world)
    world.health_extra = {"provider": "lmstudio", "model": "gemma", "lm_studio": True}
    world.tailscale_serve = "|-- / proxy http://127.0.0.1:8999\n"
    (inst.home / ".env").write_text("ANTHROPIC_API_KEY=sk-not-printed\n")
    (inst.home / "mcp.json").write_text(json.dumps({"mcpServers": {"gmail": {"command": "node"}}}))
    before = tree(tmp_path)
    assert cli.cmd_doctor(inst, world) == 0
    out = capsys.readouterr().out
    assert "FIX" not in out and "Everything looks right." in out
    assert "sk-not-printed" not in out
    assert tree(tmp_path) == before  # doctor only reads
    assert not any(c[0] == "launchctl" and c[1] != "print" for c in world.calls)


def test_doctor_says_how_to_fix_each_problem(inst, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli.shutil, "which", lambda tool, path=None: None if tool == "node" else f"/x/{tool}")
    w = World(inst)
    w.someone_else_on_port = True
    before = tree(tmp_path)
    assert cli.cmd_doctor(inst, w) == 1
    out = capsys.readouterr().out
    assert "FIX   node is missing  →  brew install node" in out
    assert "no live copy" in out and "scripts/install.sh" in out
    assert "isn't loaded  →  odie start" in out
    assert "port 8999 is taken by something else" in out
    assert "tailscale serve --bg --https=443 http://127.0.0.1:8999" in out
    assert "no Gmail app in mcp.json" in out
    assert tree(tmp_path) == before


def test_model_check(inst, world):
    lmstudio = {"provider": "lmstudio", "model": "gemma"}
    assert cli.model_check(inst, world, lmstudio).fix.startswith("open LM Studio")  # nothing answers in this world
    assert cli.model_check(inst, world, {"provider": "ollama", "model": "glm"}).ok is False
    world.loaded = True
    world.running = OLD
    assert cli.model_check(inst, world, lmstudio).ok is True
    assert cli.model_check(inst, world, {"provider": "ollama", "model": "glm"}).ok is True
    claude = {"provider": "anthropic", "model": "claude-x"}
    assert cli.model_check(inst, world, claude).ok is False
    inst.home.mkdir(parents=True, exist_ok=True)
    (inst.home / ".env").write_text("ANTHROPIC_API_KEY=k\nOPENAI_API_KEY=\n")
    assert cli.model_check(inst, world, claude).ok is True
    assert cli.model_check(inst, world, {"provider": "openai", "model": "gpt"}).ok is False  # set but empty
    assert cli.model_check(inst, world, {"provider": "my-box", "model": "m"}).ok is True  # custom: not checked here


def save_model_choice(inst: cli.Install, value) -> None:
    import sqlite3
    (inst.home / "data").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(inst.home / "data" / "assistant.db") as conn:
        conn.execute("create table settings(key text primary key, value_json text)")
        conn.execute("insert into settings values('model.chat', ?)", (json.dumps(value),))


def test_chosen_model(inst):
    assert cli.chosen_model(inst, None) == {"provider": "lmstudio", "model": "its default model"}
    assert cli.chosen_model(inst, {"status": "ok", "provider": "ollama", "model": "glm"}) == {
        "provider": "ollama", "model": "glm"}
    save_model_choice(inst, {"provider": "anthropic", "model": "claude-x"})
    assert cli.chosen_model(inst, {"status": "ok"}) == {"provider": "anthropic", "model": "claude-x"}
    assert cli.chosen_model(inst, None) == {"provider": "anthropic", "model": "claude-x"}


# ── uninstall ──

def installed_with_data(inst: cli.Install, world: World) -> None:
    (inst.home / "data").mkdir(parents=True)
    (inst.home / "data" / "assistant.db").write_text("chats")
    (inst.home / ".env").write_text("KEY=x\n")
    cli.cmd_write_command(inst, {})
    cli.cmd_start(inst, world, {})
    inst.previous_file.write_text(OLD)


def test_uninstall_keeps_data_by_default(inst, world, capsys):
    installed_with_data(inst, world)
    answers = []

    def ask(question, default):
        answers.append((question, default))
        return default

    assert cli.cmd_uninstall(inst, world, None, None, ask=ask) == 0
    assert [default for _, default in answers] == [True, False]
    assert "chats, settings, keys (.env), memories" in answers[1][0]
    assert not inst.app.exists() and not inst.plist.exists() and not inst.command.exists()
    assert not inst.previous_file.exists()
    assert "bootout" in world.events and not world.loaded
    assert (inst.home / "data" / "assistant.db").read_text() == "chats"
    assert "Your data stays" in capsys.readouterr().out


def test_uninstall_deletes_data_only_when_asked(inst, world, capsys):
    installed_with_data(inst, world)
    assert cli.cmd_uninstall(inst, world, True, True) == 0
    assert not inst.home.exists()


def test_uninstall_answered_no_removes_nothing(inst, world, capsys):
    installed_with_data(inst, world)
    asked = []

    def ask(question, default):
        asked.append(question)
        return False

    assert cli.cmd_uninstall(inst, world, None, None, ask=ask) == 0
    assert len(asked) == 1  # no data question once the app stays
    assert inst.app.exists() and inst.plist.exists() and inst.command.exists() and world.loaded


def test_uninstall_leaves_someone_elses_odie_command(inst, world):
    inst.bin_dir.mkdir(parents=True)
    inst.command.write_text("#!/bin/sh\necho another odie\n")
    cli.cmd_uninstall(inst, world, True, False)
    assert inst.command.exists()


def test_uninstall_never_deletes_a_folder_that_is_not_an_odie_home(env, tmp_path, capsys):
    inst = cli.install_from({**env, "ODIE_HOME": str(tmp_path / "documents")})
    (inst.home / "notes").mkdir(parents=True)
    w = World(inst)
    assert cli.cmd_uninstall(inst, w, True, True) == 1
    assert (inst.home / "notes").exists()
    assert cli.safe_to_delete_home(cli.install_from({**env, "ODIE_HOME": str(Path.home())})) is False
    assert cli.safe_to_delete_home(cli.install_from({**env, "ODIE_HOME": "/"})) is False


def test_uninstall_flags(env, monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "cmd_uninstall", lambda inst, runner, remove_app, delete_data: got.update(
        remove_app=remove_app, delete_data=delete_data) or 0)
    cli.main(["uninstall", "--yes", "--keep-data"], environ=env, runner=object())
    assert got == {"remove_app": True, "delete_data": False}
    cli.main(["uninstall", "--yes", "--delete-data"], environ=env, runner=object())
    assert got == {"remove_app": True, "delete_data": True}
    cli.main(["uninstall"], environ=env, runner=object())
    assert got == {"remove_app": None, "delete_data": None}


# ── the command file ──

def test_the_command_file(inst, tmp_path):
    assert cli.cmd_write_command(inst, {"ODIE_VOICE": "off", "ODIE_SCHEDULER": "0"}) == 0
    text = inst.command.read_text()
    assert os.access(inst.command, os.X_OK)
    assert text.startswith("#!/bin/sh\n" + cli.COMMAND_MARK)
    assert f"ODIE_HOME={inst.home}" in text and "ODIE_SERVICE_LABEL=dev.odie.unittest" in text
    assert "ODIE_PORT=8999" in text and "ODIE_VOICE=off" in text and "ODIE_SCHEDULER=0" in text
    assert f"ODIE_LAUNCH_AGENTS={inst.agents_dir}" in text
    assert text.rstrip().endswith(f'exec {inst.python} -P -m odie.cli "$@"')
    assert cli.is_our_command(inst.command)


def test_the_command_file_runs_the_cli_with_its_settings(inst, tmp_path):
    """The real file, run by sh: a stand-in python prints what it was given."""
    cli.cmd_write_command(inst, {})
    inst.python.parent.mkdir(parents=True)
    inst.python.write_text('#!/bin/sh\necho "$ODIE_HOME|$ODIE_SERVICE_LABEL|$ODIE_PORT|${ODIE_VOICE:-unset}|$*"\n')
    inst.python.chmod(0o755)
    out = subprocess.run([str(inst.command), "status"], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "ODIE_HOME": "/elsewhere", "ODIE_VOICE": "off"}).stdout
    assert out.strip() == f"{inst.home}|dev.odie.unittest|8999|unset|-P -m odie.cli status"


def test_the_command_file_never_replaces_someone_elses(inst, capsys):
    inst.bin_dir.mkdir(parents=True)
    inst.command.write_text("#!/bin/sh\necho mine\n")
    assert cli.cmd_write_command(inst, {}) == 1
    assert inst.command.read_text() == "#!/bin/sh\necho mine\n"


# ── serve ──

def test_serve_environment_without_tailscale(inst, world):
    env = cli.serve_environment(inst, {}, world)
    assert env == {"ODIE_HOME": str(inst.home), "ODIE_PORT": "8999", "ODIE_VOICE_PORT": "9770", "ODIE_EMBED_PORT": "9771"}


def test_serve_environment_with_tailscale_pointing_here(inst, world):
    world.tailscale_serve = "|-- / proxy http://127.0.0.1:8999\n"
    assert cli.serve_environment(inst, {}, world)["ODIE_PUBLIC_URL"] == "https://mini.tail1234.ts.net"


def test_serve_environment_keeps_what_is_set(inst, world):
    world.tailscale_serve = "|-- / proxy http://127.0.0.1:8999\n"
    env = cli.serve_environment(inst, {"ODIE_PUBLIC_URL": "https://mine", "ODIE_VOICE_PORT": "9000"}, world)
    assert "ODIE_PUBLIC_URL" not in env and "ODIE_VOICE_PORT" not in env


def test_tailscale_serves_port():
    line = "|-- / proxy http://127.0.0.1:8000\n"
    assert cli.tailscale_serves_port(line, 8000) is True
    assert cli.tailscale_serves_port(line, 8002) is False
    assert cli.tailscale_serves_port(line, 800) is False


def test_tailscale_missing(inst):
    class NoTailscale:
        def run(self, args, **kw):
            return cli.Ran(127, "tailscale: not found")
    assert cli.tailscale_phone_address(8000, NoTailscale()) == ""


def test_the_setup_link_opens_once_written(inst, world, tmp_path):
    link = tmp_path / "setup-link"
    calls = iter(range(10))

    def sleep(seconds):
        if next(calls) == 2:
            link.write_text("http://localhost:8999/api/pair/setup?token=t\n")
    world.sleep = sleep
    assert cli.open_setup_link_when_written(link, world, tries=10) is True
    assert world.events == ["open http://localhost:8999/api/pair/setup?token=t"]


def test_no_setup_link_means_no_browser(world, tmp_path):
    assert cli.open_setup_link_when_written(tmp_path / "setup-link", world, tries=3) is False
    assert world.events == []


# ── the scripts ──

def fake_bin(folder: Path, tools: dict[str, str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in tools.items():
        (folder / name).write_text("#!/bin/sh\n" + body + "\n")
        (folder / name).chmod(0o755)
    return folder


def test_scripts_parse():
    for name in ("start.sh", "install.sh", "fresh.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)]).returncode == 0, name


@pytest.mark.parametrize("live_service, home, port", [(False, ".odie", "8000"), (True, "odie-dev", "8001")])
def test_start_sh_moves_aside_when_live_odie_is_a_service(tmp_path, live_service, home, port):
    """start.sh with a pretend user folder: a stand-in uv prints what `odie serve` would get, and curl finds the
    port free."""
    user = tmp_path / "user"
    user.mkdir()
    if live_service:
        (user / ".odie" / "app" / ".git").mkdir(parents=True)
    bin_dir = fake_bin(tmp_path / "fakebin", {"uv": 'echo "uv $* :: $ODIE_HOME :: $ODIE_PORT"', "curl": "exit 7"})
    env = {"HOME": str(user), "PATH": f"{bin_dir}:/usr/bin:/bin", "FRESH_NO_BUILD": "1", "ODIE_VOICE": "off"}
    done = subprocess.run(["bash", str(ROOT / "scripts" / "start.sh")], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    assert f"uv run python -m odie.cli serve :: {user / home} :: {port}" in done.stdout
    assert ("development Odie" in done.stdout) is live_service


def test_install_sh_refuses_when_something_else_has_the_port(tmp_path):
    home = tmp_path / "home"
    bin_dir = fake_bin(tmp_path / "fakebin", {"lsof": "echo 999", "launchctl": "exit 113"})
    env = {"HOME": str(tmp_path / "user"), "PATH": f"{bin_dir}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
           "ODIE_HOME": str(home), "ODIE_SERVICE_LABEL": "dev.odie.unittest", "ODIE_PORT": "8999",
           "ODIE_BIN_DIR": str(tmp_path / "bin"), "ODIE_REPO": str(tmp_path / "no-repo")}
    assert env["ODIE_HOME"] != str(REAL_HOME)
    done = subprocess.run(["bash", str(ROOT / "scripts" / "install.sh")], capture_output=True, text=True, env=env)
    assert done.returncode == 1
    assert "Something else answers on port 8999" in done.stdout
    assert not home.exists() and not (tmp_path / "bin").exists()


def test_serve_sets_up_and_runs_uvicorn(env, world, monkeypatch, capsys):
    import sys
    import types
    inst = cli.install_from({**env, "ODIE_VOICE": "off"})
    (inst.home / "setup-link").write_text("http://localhost:8999/api/pair/setup?token=old\n")
    ran = {}
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda app, **kw: ran.update(app=app, **kw)))
    monkeypatch.setattr(os, "environ", {"PATH": "/usr/bin"})
    world.tailscale_serve = "|-- / proxy http://127.0.0.1:8999\n"
    assert cli.cmd_serve(inst, world) == 0
    assert ran == {"app": "odie.app.main:create_app", "factory": True, "host": "127.0.0.1", "port": 8999,
                   "log_level": "info"}
    assert os.environ["ODIE_HOME"] == str(inst.home) and os.environ["ODIE_VOICE_PORT"] == "9770"
    assert os.environ["ODIE_PUBLIC_URL"] == "https://mini.tail1234.ts.net"
    assert not (inst.home / "setup-link").exists()  # a stale link from an earlier start is never opened
    assert "Odie: http://localhost:8999  ·  phone: https://mini.tail1234.ts.net  ·  voice worker: off" in capsys.readouterr().out


def test_the_embedding_service_is_built_like_the_voice_worker(tmp_path):
    inst = cli.install_from({"ODIE_HOME": str(tmp_path)})
    assert inst.embed and inst.embed_port == 8000 + 772
    names = [name for name, _, _ in cli.build_steps(inst)]
    assert "the embedding service's uv sync" in names and "the voice worker's uv sync" in names
    off = cli.install_from({"ODIE_HOME": str(tmp_path), "ODIE_EMBED": "off"})
    assert not off.embed and "the embedding service's uv sync" not in [n for n, _, _ in cli.build_steps(off)]
    folder = next(folder for name, _, folder in cli.build_steps(inst) if name.startswith("the embedding"))
    assert folder == inst.app / "embed_server"


def test_the_service_environment_names_the_embedding_port(tmp_path):
    inst = cli.install_from({"ODIE_HOME": str(tmp_path), "ODIE_PORT": "8100"})
    env = cli.serve_environment(inst, {}, cli.Runner())
    assert env["ODIE_EMBED_PORT"] == "8872" and env["ODIE_VOICE_PORT"] == "8871"
    assert "ODIE_EMBED" in cli.PASSED_TO_SERVICE
