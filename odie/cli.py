"""The odie command: live Odie as a background service on this Mac, and updates that go back by themselves when
something breaks.

    odie start | stop | restart | status | pair | logs | open | update | doctor | uninstall | serve

Only the standard library is imported at the top, so the command starts instantly and still works when the app's
dependencies are broken, which is exactly when `odie update --rollback` and `odie doctor` are needed. (`serve`, which
runs Odie itself, imports uvicorn when it starts; `pair` imports Odie's own devices and database code, which are
standard library only too.)

Where everything is comes from the environment. The `odie` command file that scripts/install.sh writes sets it:
    ODIE_HOME            Odie's folder: data, keys, logs, and the live copy in app/   (~/.odie)
    ODIE_SERVICE_LABEL   the launchd service                                           (dev.odie.server)
    ODIE_PORT            where Odie answers; its voice worker is on this + 771         (8000)
    ODIE_BRANCH          what `odie update` moves to                                   (main)
    ODIE_BIN_DIR         where the odie command lives                                  (~/.local/bin)
    ODIE_LAUNCH_AGENTS   the launchd folder (tests only)                               (~/Library/LaunchAgents)
Tests and trial installs set scratch values, so they never touch the real ones.

Every outside call (launchctl, git, uv, npm, tailscale, HTTP, sleeping) goes through a Runner, which tests replace."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from odie.releases import RELEASES, follows_releases, newest_release  # standard library only, like this module

VOICE_PORT_OFFSET = 771  # 8000 → 8771: each Odie port gets its own voice worker port
EMBED_PORT_OFFSET = 772  # the embedding service's port: Odie's + 772 (ODIE_EMBED_PORT overrides)
TOOL_DIRS = ["/opt/homebrew/bin", "/usr/local/bin"]  # uv, npm, node and tailscale live here, not on launchd's PATH
SYSTEM_DIRS = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
PASSED_TO_SERVICE = ("ODIE_VOICE", "ODIE_EMBED", "ODIE_PAIRING", "ODIE_SCHEDULER", "ODIE_HOSTS")  # install-time choices the service keeps
COMMAND_MARK = "# The odie command, written by scripts/install.sh"
HEALTH_WAIT_SECONDS = 60
LOG_ROTATE_BYTES = 10 * 1024 * 1024


# ── where things are ──

@dataclass(frozen=True)
class Install:
    home: Path
    label: str
    port: int
    branch: str
    bin_dir: Path
    agents_dir: Path
    voice: bool  # whether Odie runs its local voice worker (ODIE_VOICE=off: no)
    embed: bool  # whether Odie runs its own embedding service (only with ODIE_EMBED=on)

    @property
    def app(self) -> Path:
        return self.home / "app"

    @property
    def previous_file(self) -> Path:
        return self.home / "app-previous"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def server_log(self) -> Path:
        return self.logs / "server.log"

    @property
    def update_log(self) -> Path:
        return self.logs / "update.log"

    @property
    def database(self) -> Path:
        return self.home / "data" / "assistant.db"

    @property
    def plist(self) -> Path:
        return self.agents_dir / f"{self.label}.plist"

    @property
    def command(self) -> Path:
        return self.bin_dir / "odie"

    @property
    def python(self) -> Path:
        return self.app / ".venv" / "bin" / "python"

    @property
    def voice_port(self) -> int:
        return self.port + VOICE_PORT_OFFSET

    @property
    def embed_port(self) -> int:
        return self.port + EMBED_PORT_OFFSET

    @property
    def local_url(self) -> str:
        return f"http://localhost:{self.port}"

    @property
    def api(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def domain(self) -> str:
        return f"gui/{os.getuid()}"

    @property
    def service(self) -> str:
        return f"{self.domain}/{self.label}"


def setting(environ: Mapping[str, str], name: str, default: str) -> str:
    """A setting from the environment; unset or empty means the default."""
    value = environ.get(name, "").strip()
    if value:
        return value
    return default


def voice_wanted(value: str) -> bool:
    """Whether ODIE_VOICE asks for the local voice worker. "off", "0" and "no" turn it off; anything else (or unset)
    leaves it on, the way the server reads it. Example: "off" → False, "" → True, "on" → True."""
    return value.strip().lower() not in ("off", "0", "no")


def embed_wanted(value: str) -> bool:
    """Whether ODIE_EMBED asks for Odie's own embedding service: off unless "on", "1" or "yes" (since 25 Oct 2026;
    EmbeddingGemma 2 on Ollama does the job without it). Example: "on" → True, "" → False, "off" → False."""
    return value.strip().lower() in ("on", "1", "yes")


def install_from(environ: Mapping[str, str]) -> Install:
    user_home = Path.home()
    home = Path(setting(environ, "ODIE_HOME", str(user_home / ".odie"))).expanduser()
    return Install(
        home=home,
        label=setting(environ, "ODIE_SERVICE_LABEL", "dev.odie.server"),
        port=int(setting(environ, "ODIE_PORT", "8000")),
        branch=setting(environ, "ODIE_BRANCH", RELEASES),  # what updates follow: the newest release, or a branch
        bin_dir=Path(setting(environ, "ODIE_BIN_DIR", str(user_home / ".local" / "bin"))).expanduser(),
        agents_dir=Path(setting(environ, "ODIE_LAUNCH_AGENTS", str(user_home / "Library" / "LaunchAgents"))).expanduser(),
        voice=voice_wanted(environ.get("ODIE_VOICE", "")),
        embed=embed_wanted(environ.get("ODIE_EMBED", "")),  # opt-in: ODIE_EMBED=on builds Odie's own embedding service
    )


def is_installed(inst: Install) -> bool:
    return (inst.app / ".git").exists()


def short(commit: str) -> str:
    return commit[:7]


# ── the runner: every outside call goes through here ──

@dataclass
class Ran:
    code: int
    out: str  # what it printed, stdout and stderr together


class Runner:
    """Runs commands, fetches URLs and sleeps for real. Tests pass a fake one with the same three methods."""

    def run(self, args: list[str], cwd: Path | None = None, log: Path | None = None, timeout: float = 900) -> Ran:
        try:
            done = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  timeout=timeout)
            result = Ran(done.returncode, done.stdout or "")
        except FileNotFoundError:
            result = Ran(127, f"{args[0]}: not found\n")
        except subprocess.TimeoutExpired:
            result = Ran(124, f"{args[0]}: no answer after {timeout:.0f}s\n")
        if log is not None:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                f.write(f"\n$ {' '.join(args)}   (in {cwd or Path.cwd()}, {datetime.now():%Y-%m-%d %H:%M:%S})\n")
                f.write(result.out)
                f.write(f"[exit {result.code}]\n")
        return result

    def get(self, url: str, timeout: float = 3) -> tuple[int, str] | None:
        """(status, body) from a GET, or None when nothing answers."""
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def tool_path(current: str) -> str:
    """PATH with the Homebrew folders first: launchd and some shells don't have them, and uv, npm and tailscale
    live there."""
    parts = TOOL_DIRS + [p for p in current.split(":") if p and p not in TOOL_DIRS]
    return ":".join(parts)


# ── health ──

def read_health(inst: Install, runner: Runner) -> dict | None:
    """Odie's /api/health when it says ok; None when nothing answers or the answer isn't an ok from Odie."""
    answer = runner.get(f"{inst.api}/api/health")
    if answer is None:
        return None
    status, body = answer
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("status") != "ok":
        return None
    return data


def page_loads(inst: Install, runner: Runner) -> bool:
    answer = runner.get(f"{inst.api}/", timeout=5)
    return answer is not None and answer[0] == 200


def wait_until_healthy(inst: Install, runner: Runner, seconds: int = HEALTH_WAIT_SECONDS) -> bool:
    """Up to `seconds`, checking every 2: /api/health says ok and the app page loads."""
    for _ in range(max(1, seconds // 2)):
        runner.sleep(2)
        if read_health(inst, runner) is not None and page_loads(inst, runner):
            return True
    return False


# ── the launchd service ──

def service_info(inst: Install, runner: Runner) -> dict | None:
    """What launchd says about the service (state, pid, runs), or None when it isn't loaded."""
    printed = runner.run(["launchctl", "print", inst.service], timeout=10)
    if printed.code != 0:
        return None
    info: dict[str, str] = {}
    for line in printed.out.splitlines():
        match = re.match(r"^\t(state|pid|runs|last exit code) = (.+)$", line)
        if match and match.group(1) not in info:  # the service's own lines come first, nested ones later
            info[match.group(1)] = match.group(2).strip()
    return info


def service_loaded(inst: Install, runner: Runner) -> bool:
    return service_info(inst, runner) is not None


def service_env(inst: Install, environ: Mapping[str, str]) -> dict[str, str]:
    """The environment launchd starts `odie serve` with: where it lives, what its updates follow, and the install-time
    choices. The branch goes in too: the app's Check now and Update run in the service, so without it an install that
    follows main (ODIE_BRANCH=main) would look for releases there and find none (15 Oct)."""
    env = {
        "PATH": ":".join(TOOL_DIRS + SYSTEM_DIRS),
        "ODIE_HOME": str(inst.home),
        "ODIE_PORT": str(inst.port),
        "ODIE_SERVICE_LABEL": inst.label,
        "ODIE_BRANCH": inst.branch,
        "PYTHONUNBUFFERED": "1",  # log lines reach the log as they happen
    }
    for name in PASSED_TO_SERVICE:
        if environ.get(name):
            env[name] = environ[name]
    return env


def plist_contents(inst: Install, environ: Mapping[str, str]) -> dict:
    """The service: `odie serve` from the live copy at every login, restarted if it stops (KeepAlive). Both of its
    outputs go to logs/server.log."""
    return {
        "Label": inst.label,
        "ProgramArguments": [str(inst.python), "-P", "-m", "odie.cli", "serve"],
        "WorkingDirectory": str(inst.app),
        "EnvironmentVariables": service_env(inst, environ),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(inst.server_log),
        "StandardErrorPath": str(inst.server_log),
    }


def log_too_big(size: int) -> bool:
    """Whether the server log should be moved aside before a start (launchd only ever appends to it).
    Example: 12 MB → True (it becomes server.log.1, replacing an older one); 3 MB → False."""
    return size > LOG_ROTATE_BYTES


def prepare_logs(inst: Install) -> None:
    inst.logs.mkdir(parents=True, exist_ok=True)
    if inst.server_log.exists() and log_too_big(inst.server_log.stat().st_size):
        inst.server_log.replace(inst.logs / "server.log.1")


def write_plist(inst: Install, environ: Mapping[str, str]) -> None:
    inst.agents_dir.mkdir(parents=True, exist_ok=True)
    with inst.plist.open("wb") as f:
        plistlib.dump(plist_contents(inst, environ), f)


def load_service(inst: Install, runner: Runner) -> bool:
    """Hands the service file to launchd, which starts it. A service just unloaded can take a moment to go, so this
    tries a few times."""
    for _ in range(5):
        if runner.run(["launchctl", "bootstrap", inst.domain, str(inst.plist)], timeout=30).code == 0:
            return True
        runner.sleep(2)
    return False


def unload_service(inst: Install, runner: Runner) -> None:
    """Stops the service and waits (up to 10 seconds) until launchd has really let it go."""
    runner.run(["launchctl", "bootout", inst.service], timeout=30)
    for _ in range(20):
        if not service_loaded(inst, runner):
            return
        runner.sleep(0.5)


def listener_pid(port: int, runner: Runner) -> int | None:
    """The process listening on the port, or None when nothing is."""
    found = runner.run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], timeout=10)
    if found.code != 0:
        return None
    pids = found.out.split()
    if not pids or not pids[0].isdigit():
        return None
    return int(pids[0])


def port_taken_by_someone_else(inst: Install, runner: Runner) -> bool:
    """Whether the port is held by something that isn't this install's service, so starting would collide.
    Examples on port 8000: start.sh's Odie listening while dev.odie.server isn't loaded → True (stop it first);
    dev.odie.server loaded and its pid is the listener → False (it's ours); nothing listening → False."""
    listener = listener_pid(inst.port, runner)
    if listener is None:
        return False
    info = service_info(inst, runner)
    if info is None:
        return True
    return info.get("pid") != str(listener)


# ── what's checked out ──

def git(inst: Install, runner: Runner, *args: str, log: Path | None = None) -> Ran:
    return runner.run(["git", "-C", str(inst.app), *args], log=log, timeout=300)


def current_commit(inst: Install, runner: Runner) -> str:
    return git(inst, runner, "rev-parse", "HEAD").out.strip()


def copy_has_changes(inst: Install, runner: Runner) -> bool:
    """Whether someone edited the live copy (it should only ever change through `odie update`)."""
    return git(inst, runner, "status", "--porcelain").out.strip() != ""


def short_subject(subject: str) -> str:
    """A commit subject short enough for one status line.
    Examples: "Merge pull request #41 from someone/schema-cleanup" → "Merge #41";
    "Calendar watch reads whole days for date_from" → "Calendar watch reads whole days for dat…" (40 characters)."""
    merge = re.match(r"Merge pull request #(\d+)", subject)
    if merge:
        return f"Merge #{merge.group(1)}"
    if len(subject) <= 40:
        return subject
    return subject[:39] + "…"


def version_line(inst: Install, runner: Runner) -> str:
    """ "b76540d (Merge #41, 2026-10-11)" for what's checked out, or "unknown" when git can't say."""
    shown = git(inst, runner, "log", "-1", "--format=%h%x09%s%x09%cd", "--date=short")
    parts = shown.out.strip().split("\t")
    if shown.code != 0 or len(parts) != 3:
        return "unknown"
    commit, subject, date = parts
    return f"{commit} ({short_subject(subject)}, {date})"


def remembered_previous(inst: Install) -> str:
    if not inst.previous_file.exists():
        return ""
    return inst.previous_file.read_text().strip()


def remember_rollback_point(inst: Install, commit: str) -> None:
    inst.previous_file.write_text(commit + "\n")


# ── building ──

def build_steps(inst: Install) -> list[tuple[str, list[str], Path]]:
    """What a checkout needs before it can run: Python packages, the voice worker's (unless voice is off), the embedding
    service's (only with ODIE_EMBED=on), and the web app."""
    steps = [("uv sync", ["uv", "sync", "--frozen"], inst.app)]
    if inst.voice:
        steps.append(("the voice worker's uv sync", ["uv", "sync", "--frozen"], inst.app / "voice_server"))
    if inst.embed:
        steps.append(("the embedding service's uv sync", ["uv", "sync", "--frozen"], inst.app / "embed_server"))
    steps.append(("npm ci", ["npm", "ci"], inst.app / "web"))
    steps.append(("npm run build", ["npm", "run", "build"], inst.app / "web"))
    return steps


def check_out_and_build(inst: Install, runner: Runner, commit: str) -> str | None:
    """Checks out the commit and builds it, everything going to logs/update.log. Returns the step that failed, or
    None when all of them worked."""
    if git(inst, runner, "checkout", "-q", "--detach", commit, log=inst.update_log).code != 0:
        return f"git checkout {short(commit)}"
    for name, args, folder in build_steps(inst):
        if runner.run(args, cwd=folder, log=inst.update_log).code != 0:
            return name
    return None


def restart_and_check(inst: Install, runner: Runner) -> bool:
    """Restarts the service in place and waits up to a minute for it to be healthy."""
    runner.run(["launchctl", "kickstart", "-k", inst.service], timeout=60)
    return wait_until_healthy(inst, runner)


# ── odie start / stop / restart ──

def cmd_start(inst: Install, runner: Runner, environ: Mapping[str, str]) -> int:
    # 1. There has to be an installed copy to run.
    if not is_installed(inst):
        print(f"Odie isn't installed at {inst.app}: run scripts/install.sh from the work folder.")
        return 1
    # 2. Already running: nothing to do.
    if service_loaded(inst, runner):
        print(f"Odie is already running: {inst.local_url}  (odie status for more)")
        return 0
    # 3. The port has to be free, or held by this service.
    if port_taken_by_someone_else(inst, runner):
        print(f"Something else is answering on port {inst.port} (scripts/start.sh in a terminal?). Stop it first.")
        return 1
    # 4. Write the service file and load it: Odie starts now, and at every login from now on.
    nothing_paired_before = paired_device_count(inst) == 0
    prepare_logs(inst)
    write_plist(inst, environ)
    if not load_service(inst, runner):
        print(f"launchd wouldn't load {inst.plist}.")
        return 1
    # 5. Wait until it answers.
    print("Starting Odie…")
    if wait_until_healthy(inst, runner):
        print(f"Odie is running: {inst.local_url}")
        phone = tailscale_phone_address(inst.port, runner)
        if phone:
            print(f"  phone:  {phone}  (open this on your phone; Settings → Phone has the steps)")
        # 6. A first start: say how a browser that isn't this Mac's gets in.
        if nothing_paired_before and pairing_asked_for(inst, environ):
            print(PAIRING_HINT)
        return 0
    print(f"Odie started but isn't answering yet. `odie logs -e` shows what went wrong ({inst.server_log}).")
    return 1


def cmd_stop(inst: Install, runner: Runner) -> int:
    was_loaded = service_loaded(inst, runner)
    if was_loaded:
        unload_service(inst, runner)
    # Without its service file, launchd doesn't start it at the next login either: it stays stopped until odie start.
    inst.plist.unlink(missing_ok=True)
    if was_loaded:
        print("Odie stopped. It stays stopped, even after a restart of the Mac, until `odie start`.")
    else:
        print("Odie wasn't running.")
    return 0


def cmd_restart(inst: Install, runner: Runner, environ: Mapping[str, str]) -> int:
    """Stop (when it's running) and start. install.sh uses it, so a reinstall picks up the new service file."""
    if service_loaded(inst, runner):
        print("Stopping Odie…")
        unload_service(inst, runner)
        inst.plist.unlink(missing_ok=True)
    return cmd_start(inst, runner, environ)


# ── odie status ──

def started_at(pid: str, runner: Runner, now: datetime) -> str:
    """When the process started, as "09:12 today" or "Oct 10, 09:12"; "" when ps can't say."""
    shown = runner.run(["ps", "-o", "lstart=", "-p", pid], timeout=10)
    try:
        when = datetime.strptime(" ".join(shown.out.split()), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return ""
    if when.date() == now.date():
        return f"{when:%H:%M} today"
    return f"{when:%b %d, %H:%M}"


def tailscale_serves_port(serve_status: str, port: int) -> bool:
    """Whether `tailscale serve status` forwards to this port on this Mac.
    Example: a line "|-- / proxy http://127.0.0.1:8000" → True for 8000, False for 8002 (and False for 800)."""
    return re.search(rf"127\.0\.0\.1:{port}\b", serve_status) is not None


def tailscale_phone_address(port: int, runner: Runner) -> str:
    """The phone's https address when `tailscale serve` points at this port, else ""."""
    serve_status = runner.run(["tailscale", "serve", "status"], timeout=10)
    if serve_status.code != 0 or not tailscale_serves_port(serve_status.out, port):
        return ""
    status = runner.run(["tailscale", "status", "--json"], timeout=10)
    try:
        name = json.loads(status.out)["Self"]["DNSName"].rstrip(".")
    except (ValueError, KeyError, TypeError, AttributeError):
        return ""
    if not name:
        return ""
    return f"https://{name}"


PROVIDER_NAMES = {"lmstudio": "LM Studio", "ollama": "Ollama", "anthropic": "Claude", "openai": "OpenAI",
                  "openrouter": "OpenRouter", "gemini": "Gemini"}


def read_setting(inst: Install, key: str) -> object | None:
    """A setting saved in Odie's database, read (read-only); None when it isn't there or can't be read."""
    if not inst.database.exists():
        return None
    try:
        with sqlite3.connect(f"file:{inst.database}?mode=ro", uri=True, timeout=2) as conn:
            row = conn.execute("select value_json from settings where key=?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return None


def saved_model(inst: Install) -> dict | None:
    """The model chosen in Settings > Brain, read (read-only) from Odie's database; None when none was chosen."""
    chosen = read_setting(inst, "model.chat")
    if not isinstance(chosen, dict) or "provider" not in chosen:
        return None
    return chosen


def chosen_model(inst: Install, health: dict | None) -> dict:
    """Which model Odie uses, as {"provider", "model"}: from its health answer, else from its saved settings (an Odie
    with pairing on tells only paired devices), else LM Studio's default.
    Examples: health {"status": "ok", "provider": "ollama", "model": "glm"} → Ollama, glm;
    health {"status": "ok"} with Claude saved in Settings → Claude and its model;
    nothing answers and nothing saved → {"provider": "lmstudio", "model": "its default model"}."""
    if health is not None and "provider" in health:
        return {"provider": health["provider"], "model": health.get("model", "")}
    saved = saved_model(inst)
    if saved is not None:
        return {"provider": saved["provider"], "model": saved.get("model", "")}
    return {"provider": "lmstudio", "model": "its default model"}


def model_line(chosen: dict) -> str:
    """ "Ollama · glm-5.3-flash:cloud" """
    provider = chosen["provider"]
    name = PROVIDER_NAMES.get(provider, provider)
    return f"{name} · {chosen['model']}"


def cmd_status(inst: Install, runner: Runner, now: datetime | None = None) -> int:
    now = now or datetime.now()
    if not is_installed(inst):
        print(f"Odie isn't installed at {inst.app}: run scripts/install.sh from the work folder.")
        return 1
    version = version_line(inst, runner)
    info = service_info(inst, runner)
    if info is None:
        print(f"Odie is stopped  ·  version {version}")
        if port_taken_by_someone_else(inst, runner):
            print(f"  port {inst.port} is answered by something else (scripts/start.sh?)")
        print("  start it with: odie start")
        return 1
    health = read_health(inst, runner)
    if health is not None:
        state = "healthy"
    else:
        state = "not answering (odie logs -e)"
    print(f"Odie is running  ·  version {version}  ·  {state}")
    print(f"  this Mac:  {inst.local_url}")
    phone = tailscale_phone_address(inst.port, runner)
    if phone:
        print(f"  phone:     {phone}")
    print(f"  model:     {model_line(chosen_model(inst, health))}")
    started = "unknown"
    if info.get("pid"):
        started = started_at(info["pid"], runner, now) or "unknown"
    restarts = max(0, int(info.get("runs", "1")) - 1)
    print(f"  started:   {started}  ·  restarts since it was loaded: {restarts}")
    if health is None:
        return 1
    return 0


# ── odie pair ──

PAIRING_HINT = ("Pairing: this Mac's browser opens the setup link. On another computer or over SSH, run `odie pair` "
                "and type the code.")
DARK_ON_LIGHT = "\x1b[30;107m"  # black on bright white, whatever the terminal's own colours
PLAIN = "\x1b[0m"
HALF_BLOCKS = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}


def paired_device_count(inst: Install) -> int:
    """How many devices are paired, read (read-only) from Odie's database; 0 when there's no database yet."""
    if not inst.database.exists():
        return 0
    try:
        with sqlite3.connect(f"file:{inst.database}?mode=ro", uri=True, timeout=2) as conn:
            row = conn.execute("select count(*) from devices").fetchone()
    except sqlite3.Error:
        return 0
    return row[0]


def pairing_asked_for(inst: Install, environ: Mapping[str, str]) -> bool:
    """Whether this Odie asks browsers to pair: ODIE_PAIRING wins, as in the server, else the choice it saved. An Odie
    that hasn't saved one yet is a new install, and those start with pairing on.
    Examples: ODIE_PAIRING=off → False; saved {"on": false} → False; saved {"on": true} → True; nothing saved → True."""
    from odie import devices  # standard library only, like this module
    forced = devices.forced_choice(environ.get("ODIE_PAIRING", ""))
    if forced is not None:
        return forced
    saved = read_setting(inst, "pairing")  # odie.devices saves the choice under this key
    if not isinstance(saved, dict):
        return True
    return bool(saved.get("on"))


def new_pairing_code(inst: Install) -> str:
    """A fresh one-time code, made by the same code as Settings → Devices, in this install's database."""
    from odie import devices
    from odie.store.db import Store
    store = Store(inst.database)
    try:
        return devices.new_code(store)
    finally:
        store.close()


def terminal_qr(text: str, border: int = 2) -> list[str]:
    """`text` as a QR code drawn with characters, two rows of the code per line of text. Each character is the upper
    and the lower module: dark over light → "▀", light over dark → "▄", both dark → "█", both light → " "."""
    from odie import qr  # standard library only, like this module
    matrix = qr.encode(text)
    size = len(matrix)

    def dark(row: int, col: int) -> bool:
        inside = 0 <= row < size and 0 <= col < size
        return inside and matrix[row][col]

    lines = []
    for top in range(-border, size + border, 2):
        chars = []
        for col in range(-border, size + border):
            chars.append(HALF_BLOCKS[(dark(top, col), dark(top + 1, col))])
        lines.append(DARK_ON_LIGHT + "".join(chars) + PLAIN)
    return lines


def cmd_pair(inst: Install, runner: Runner, environ: Mapping[str, str]) -> int:
    """A one-time code for a new device, for when the Mac's own browser isn't the one in front of you (over SSH, or
    another computer)."""
    # 1. There has to be an Odie that has started at least once: its first start makes the database.
    if not is_installed(inst):
        print(f"Odie isn't installed at {inst.app}: run scripts/install.sh from the work folder.")
        return 1
    if not inst.database.exists():
        print("Odie hasn't started yet, so there's nothing to pair with: odie start first.")
        return 1
    # 2. With pairing off, every browser that reaches Odie gets in, so there's no code to type.
    if not pairing_asked_for(inst, environ):
        print("Pairing is off on this Odie: any browser that reaches it gets in, no code needed. "
              "Settings → Devices turns it on.")
        return 0
    # 3. A fresh code, saved where Odie checks it.
    code = new_pairing_code(inst)
    # 4. Where to type it.
    phone = tailscale_phone_address(inst.port, runner)
    print(f"Pairing code: {code}   (valid once, for 10 minutes)")
    print("Type it on the \"This Odie is private\" screen at")
    print(f"  this Mac:  {inst.local_url}")
    if phone:
        print(f"  phone:     {phone}")
        # 5. Or the phone scans it: the link opens Odie with the code filled in, as Settings → Devices' QR does.
        print("or scan this with the phone's camera:")
        for line in terminal_qr(f"{phone}/#pair={code}"):
            print(line)
    return 0


# ── odie logs / open ──

class ProblemFilter:
    """Keeps the lines that matter when something is wrong: warnings, errors and tracebacks, with the lines that
    belong to them, and drops the rest. A traceback ends at the exception's own line.
    Example, line by line:
        2026-10-11 09:12:00,1 odie INFO started          dropped (an INFO record)
        2026-10-11 09:12:05,2 odie ERROR turn failed     kept (an ERROR record)
        Traceback (most recent call last):               kept (part of that error)
          File "x.py", line 3, in f                      kept
        ValueError: bad                                  kept (the exception's line ends the traceback)
        Odie: http://localhost:8000                      dropped (after the traceback)
        INFO:     127.0.0.1 - "GET / HTTP/1.1" 200       dropped (a new record, and an INFO one)"""

    RECORD = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}|(DEBUG|INFO|WARNING|ERROR|CRITICAL):)")
    PROBLEM = re.compile(r"^(WARNING|ERROR|CRITICAL):|\s(WARNING|ERROR|CRITICAL)\s")

    def __init__(self) -> None:
        self.inside_problem = False
        self.in_traceback_body = False  # past a traceback's indented lines, waiting for the exception's line

    def keep(self, line: str) -> bool:
        if self.RECORD.match(line):
            self.inside_problem = self.PROBLEM.search(line) is not None
            self.in_traceback_body = False
            return self.inside_problem
        if line.startswith("Traceback"):
            self.inside_problem = True
            self.in_traceback_body = False
            return True
        if not self.inside_problem:
            return False
        if line.startswith((" ", "\t")):
            self.in_traceback_body = True
            return True
        if self.in_traceback_body:
            # "ValueError: bad": the last line of the traceback
            self.inside_problem = False
            self.in_traceback_body = False
        return True


def last_lines(path: Path, count: int, errors_only: bool) -> list[str]:
    lines = path.read_text(errors="replace").splitlines()
    if errors_only:
        problems = ProblemFilter()
        lines = [line for line in lines if problems.keep(line)]
    return lines[-count:]


def follow(path: Path, runner: Runner, errors_only: bool, keep_going: Callable[[], bool]) -> None:
    """Prints lines as they're added to the log until Ctrl-C (or keep_going says stop, in tests)."""
    problems = ProblemFilter()
    with path.open(errors="replace") as f:
        f.seek(0, os.SEEK_END)
        while keep_going():
            line = f.readline()
            if not line:
                runner.sleep(0.5)
                continue
            if errors_only and not problems.keep(line.rstrip("\n")):
                continue
            print(line, end="", flush=True)


def cmd_logs(inst: Install, runner: Runner, lines: int | None, errors_only: bool, keep_following: bool,
             keep_going: Callable[[], bool] = lambda: True) -> int:
    """`odie logs` shows the last 20 lines and follows; `-n 200` shows the last 200 and stops (add -f to follow);
    -e keeps only warnings, errors and tracebacks."""
    if not inst.server_log.exists():
        print(f"No log yet at {inst.server_log}.")
        return 1
    if lines is None:
        count = 20
        following = True
    else:
        count = lines
        following = keep_following
    for line in last_lines(inst.server_log, count, errors_only):
        print(line)
    if following:
        try:
            follow(inst.server_log, runner, errors_only, keep_going)
        except KeyboardInterrupt:
            pass
    return 0


SETUP_LINK_JUST_OPENED = 90  # seconds: within this of the service writing its setup link, it has opened that link itself
OPEN_WAITS_FOR_LINK = 20  # seconds `odie open` gives a just-started service to write its setup link


def open_link_or_say_so(link_file: Path, runner: Runner) -> int:
    """The setup link is there: opened by the service itself if it's young (then nothing more is opened, and this says
    so), opened here if it's old (that tab was closed). Link 5 s old -> says "already open", opens nothing; 10 min old
    -> opens the link."""
    age = time.time() - link_file.stat().st_mtime
    if age < SETUP_LINK_JUST_OPENED:
        print("Setup is already open in your browser: the tab that pairs this Mac.")
        return 0
    return runner.run(["open", link_file.read_text().strip()], timeout=10).code


def needs_no_setup_link(inst: Install, runner: Runner) -> bool:
    """Whether the plain address is the right thing to open: Odie answers /api/health with its name, which it only does
    for a paired browser or with pairing off. Health {"status":"ok","name":"Odie"} -> True; {"status":"ok"} (nothing
    paired yet: the service is about to write a setup link) -> False; nothing answering yet -> False."""
    health = read_health(inst, runner)
    return health is not None and "name" in health


def cmd_open(inst: Install, runner: Runner) -> int:
    """Opens Odie in this Mac's browser. While nothing is paired the service writes a one-time setup link at start and
    opens it itself (open_setup_link_when_written), so right after an install a second tab would only show a page that
    can't load until that first tab has paired: then this says so and opens nothing (the owner saw two tabs, one blank,
    20 Oct 2026). The installer runs this before the service has written that link, so with the service loaded and
    nothing paired it waits up to OPEN_WAITS_FOR_LINK seconds for the link (the owner saw the two tabs again on 0.2.3).
    An older setup link (the tab was closed) is opened instead of the plain address, which can't pair.
    Fresh install, link appears 3 s later -> nothing opened, "already open"; paired -> http://localhost:8000 at once;
    service not loaded -> http://localhost:8000 at once; unpaired and no link after 20 s -> http://localhost:8000."""
    link_file = inst.home / "setup-link"
    for _ in range(OPEN_WAITS_FOR_LINK):
        if link_file.exists() and link_file.stat().st_size > 0:
            return open_link_or_say_so(link_file, runner)
        if needs_no_setup_link(inst, runner) or not service_loaded(inst, runner):
            break
        runner.sleep(1)
    return runner.run(["open", inst.local_url], timeout=10).code


# ── odie update ──

def move_to(inst: Install, runner: Runner, target: str, back_to: str) -> int:
    """Steps 3 to 6 of an update: build the target, restart, check, and go back to `back_to` if any of it fails."""
    # 3. Check out the target and build it (output in logs/update.log, not on the screen).
    failed_step = check_out_and_build(inst, runner, target)
    # 4. The build failed: back to the previous commit and rebuild it. Odie was never stopped.
    if failed_step is not None:
        check_out_and_build(inst, runner, back_to)
        print(f"{failed_step} failed, so Odie stays on {short(back_to)} and kept running. Details: {inst.update_log}")
        return 1
    if not service_loaded(inst, runner):
        print(f"Now on {version_line(inst, runner)}. Odie is stopped: `odie start` runs it.")
        return 0
    # 5. Restart the service and wait up to a minute for /api/health and the app page.
    print(f"Built {short(target)}; restarting Odie…")
    if restart_and_check(inst, runner):
        print(f"Odie is on {version_line(inst, runner)} and healthy.")
        return 0
    # 6. Not healthy: back to the previous commit, rebuild, restart, and check again.
    print(f"Odie on {short(target)} isn't healthy; going back to {short(back_to)}…")
    check_out_and_build(inst, runner, back_to)
    if restart_and_check(inst, runner):
        print(f"Rolled back to {short(back_to)}; Odie is healthy again.")
        return 1
    print(f"Even {short(back_to)} isn't healthy. The error log: {inst.server_log} (odie logs -e).")
    return 2


def update_target(inst: Install, runner: Runner) -> str:
    """What `odie update` moves to: the newest release tag, or origin/<branch> for an install that follows a branch.
    Example: tags v0.1.0 and v0.2.0, following releases -> "v0.2.0"; ODIE_BRANCH=main -> "origin/main";
    following releases with no tag yet -> "" (nothing to update to)."""
    if not follows_releases(inst.branch):
        return f"origin/{inst.branch}"
    tags = git(inst, runner, "tag", "-l", "v*").out.split()
    return newest_release(tags) or ""


def update(inst: Install, runner: Runner, force: bool) -> int:
    # 1. Remember the current commit as the rollback point.
    current = current_commit(inst, runner)
    # 2. Fetch; if the newest release (or origin/<branch>) is the current commit, there's nothing to do (unless --force).
    if git(inst, runner, "fetch", "-q", "--tags", "origin", log=inst.update_log).code != 0:
        print(f"Couldn't fetch the newest version (no network?). Details: {inst.update_log}")
        return 1
    target = update_target(inst, runner)
    newest = ""
    if target:
        newest = git(inst, runner, "rev-parse", f"{target}^{{commit}}").out.strip()
    if not newest:
        print(f"There's no {target or 'release'} to update to yet.")
        return 1
    pinned = os.environ.get("ODIE_UPDATE_TO", "")  # the app's button: the commit its check showed (odie.update.start)
    if pinned and newest != pinned:
        print(f"The newest version changed since the app looked ({short(pinned)} then, {short(newest)} now): check again.")
        return 1
    if newest == current and not force:
        print(f"Already up to date: {version_line(inst, runner)}")
        return 0
    # Rebuilding the same commit (--force) keeps the rollback point from the last real update.
    if newest != current:
        remember_rollback_point(inst, current)
    print(f"Updating {short(current)} → {short(newest)}…")
    return move_to(inst, runner, newest, back_to=current)


def roll_back(inst: Install, runner: Runner) -> int:
    """Steps 3 to 5 with the remembered commit. The commit it leaves becomes the new rollback point, so a rollback
    is undone the same way."""
    previous = remembered_previous(inst)
    if not previous:
        print("No earlier version is remembered yet (that happens on the first `odie update`).")
        return 1
    current = current_commit(inst, runner)
    if previous == current:
        print(f"Already on the remembered version, {short(previous)}.")
        return 0
    remember_rollback_point(inst, current)
    print(f"Going back to {short(previous)}…")
    return move_to(inst, runner, previous, back_to=current)


def cmd_update(inst: Install, runner: Runner, force: bool = False, rollback: bool = False) -> int:
    if not is_installed(inst):
        print(f"Odie isn't installed at {inst.app}: run scripts/install.sh from the work folder.")
        return 1
    if copy_has_changes(inst, runner):
        print(f"{inst.app} has local changes, and only `odie update` should change it. "
              f"See them with: git -C {inst.app} status")
        return 1
    inst.logs.mkdir(parents=True, exist_ok=True)
    if rollback:
        return roll_back(inst, runner)
    return update(inst, runner, force)


# ── odie doctor ──

@dataclass
class Check:
    ok: bool
    what: str
    fix: str = ""


def env_file_has(path: Path, name: str) -> bool:
    """Whether the .env sets `name` to something (the value itself is never read out or printed)."""
    if not path.exists():
        return False
    for line in path.read_text(errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name and value.strip():
            return True
    return False


CLOUD_KEYS = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "gemini": "GEMINI_API_KEY",
              "anthropic": "ANTHROPIC_API_KEY"}


def model_check(inst: Install, runner: Runner, chosen: dict) -> Check:
    """Whether the chosen model's provider can answer: LM Studio and Ollama by asking them, a cloud provider by its
    key being set."""
    provider = chosen["provider"]
    model = chosen["model"]
    if provider == "lmstudio":
        if runner.get("http://127.0.0.1:1234/v1/models") is not None:
            return Check(True, f"LM Studio answers ({model})")
        return Check(False, "LM Studio isn't answering", "open LM Studio and start its server (port 1234)")
    if provider == "ollama":
        if runner.get("http://127.0.0.1:11434/api/version") is not None:
            return Check(True, f"Ollama answers ({model})")
        return Check(False, "Ollama isn't answering", "open the Ollama app (or run: ollama serve)")
    key = CLOUD_KEYS.get(provider)
    if key is None:
        return Check(True, f"the model: {provider} (a custom endpoint; Settings > Brain tests it)")
    if env_file_has(inst.home / ".env", key):
        return Check(True, f"{PROVIDER_NAMES[provider]}: its key is set ({model})")
    return Check(False, f"{PROVIDER_NAMES[provider]} has no key ({key})", "add the key in Settings > Providers")


def gmail_configured(inst: Install) -> bool:
    """Whether mcp.json lists a Gmail app (the mail watch reads mail through it). Example: a server named "gmail" or
    run from a gmail package -> True; only a notes app -> False."""
    path = inst.home / "mcp.json"
    if not path.exists():
        return False
    try:
        servers = json.loads(path.read_text()).get("mcpServers", {})
    except (ValueError, AttributeError):
        return False
    return any("gmail" in json.dumps({name: spec}).lower() for name, spec in servers.items())


def doctor_checks(inst: Install, runner: Runner) -> list[Check]:
    checks = []
    for tool in ("uv", "git", "node", "npm"):
        if shutil.which(tool, path=tool_path(os.environ.get("PATH", ""))):
            checks.append(Check(True, f"{tool} is installed"))
        else:
            checks.append(Check(False, f"{tool} is missing", f"brew install {tool}"))

    if not is_installed(inst):
        checks.append(Check(False, f"no live copy at {inst.app}", "run scripts/install.sh from the work folder"))
    elif copy_has_changes(inst, runner):
        checks.append(Check(False, f"{inst.app} has local changes", f"git -C {inst.app} status, then odie update"))
    else:
        checks.append(Check(True, f"the live copy is clean ({version_line(inst, runner)})"))

    loaded = service_loaded(inst, runner)
    if loaded:
        checks.append(Check(True, f"the service {inst.label} is loaded"))
    else:
        checks.append(Check(False, f"the service {inst.label} isn't loaded", "odie start"))

    if port_taken_by_someone_else(inst, runner):
        checks.append(Check(False, f"port {inst.port} is taken by something else", "stop it (scripts/start.sh?)"))
    elif listener_pid(inst.port, runner) is not None:
        checks.append(Check(True, f"port {inst.port} answers"))
    else:
        checks.append(Check(False, f"nothing answers on port {inst.port}", "odie start, then odie logs -e"))

    health = read_health(inst, runner)
    if health is not None:
        checks.append(Check(True, "/api/health says ok"))
    else:
        checks.append(Check(False, "/api/health doesn't say ok", "odie logs -e"))

    if (inst.home / ".env").exists():
        checks.append(Check(True, f"{inst.home / '.env'} exists"))
    else:
        checks.append(Check(False, f"no {inst.home / '.env'} yet", "finish setup in the browser (odie open)"))

    checks.append(model_check(inst, runner, chosen_model(inst, health)))

    if tailscale_phone_address(inst.port, runner):
        checks.append(Check(True, f"Tailscale serve points at port {inst.port}"))
    else:
        checks.append(Check(False, f"Tailscale serve doesn't point at port {inst.port} (no phone address)",
                            f"tailscale serve --bg --https=443 http://127.0.0.1:{inst.port}"))

    if gmail_configured(inst):
        checks.append(Check(True, "a Gmail app is connected for the mail watch"))
    else:
        checks.append(Check(False, "no Gmail app in mcp.json (no mail watch)",
                            "connect mail in Settings > Connected apps"))
    return checks


def cmd_doctor(inst: Install, runner: Runner) -> int:
    """Checks everything Odie needs and says how to fix what's wrong. It only reads; it never changes anything."""
    checks = doctor_checks(inst, runner)
    for check in checks:
        if check.ok:
            print(f"  ok    {check.what}")
        else:
            print(f"  FIX   {check.what}  →  {check.fix}")
    problems = [c for c in checks if not c.ok]
    if problems:
        print(f"{len(problems)} thing(s) to fix.")
        return 1
    print("Everything looks right.")
    return 0


# ── odie uninstall ──

def ask_yes_no(question: str, default: bool) -> bool:
    if default:
        hint = "[Y/n]"
    else:
        hint = "[y/N]"
    try:
        answer = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def safe_to_delete_home(inst: Install) -> bool:
    """Whether the home folder is something `uninstall` may delete: an Odie home, never the user's own folder or
    one above it.
    Examples: ~/.odie with data/ inside → True; ~ itself → False; / → False; ~/Documents (no data/, .env or logs/)
    → False."""
    home = inst.home.resolve()
    user_home = Path.home().resolve()
    if home == Path("/") or home == user_home or home in user_home.parents:
        return False
    return any((home / part).exists() for part in ("data", ".env", "logs"))


def is_our_command(path: Path) -> bool:
    """Whether the file at ~/.local/bin/odie is the command install.sh wrote (never someone else's odie)."""
    try:
        return COMMAND_MARK in path.read_text()
    except (OSError, UnicodeDecodeError):
        return False


def cmd_uninstall(inst: Install, runner: Runner, remove_app: bool | None, delete_data: bool | None,
                  ask: Callable[[str, bool], bool] = ask_yes_no) -> int:
    """Two separate questions: the app and its service (yes by default), then the data (no by default). The flags
    answer them for scripts and tests."""
    # Question 1: the service, the command and the app copy.
    if remove_app is None:
        remove_app = ask(f"Remove Odie's service ({inst.label}), the odie command and the app copy in {inst.app}?", True)
    if not remove_app:
        print("Nothing removed.")
        return 0
    if service_loaded(inst, runner):
        unload_service(inst, runner)
    inst.plist.unlink(missing_ok=True)
    if is_our_command(inst.command):
        inst.command.unlink()
    shutil.rmtree(inst.app, ignore_errors=True)
    inst.previous_file.unlink(missing_ok=True)
    print(f"Removed the service, the odie command and {inst.app}.")

    # Question 2: the data, which is yours (chats, settings, keys, memories).
    if delete_data is None:
        delete_data = ask(f"Also delete your data in {inst.home}? That's your chats, settings, keys (.env), "
                          f"memories and logs, and can't be undone.", False)
    if not delete_data:
        print(f"Your data stays in {inst.home}: scripts/install.sh (or scripts/start.sh) carries on from it.")
        return 0
    if not safe_to_delete_home(inst):
        print(f"{inst.home} doesn't look like an Odie home, so it was left alone.")
        return 1
    shutil.rmtree(inst.home)
    print(f"Deleted {inst.home}.")
    return 0


# ── the command file (written by install.sh) ──

def command_file_text(inst: Install, environ: Mapping[str, str]) -> str:
    """~/.local/bin/odie: runs this module with the live copy's own Python, for this install. It sets where
    everything is (so the command always means the live Odie, whatever the shell has set) and the install-time
    choices. `-P` keeps a folder named odie in the current directory (the work folder) from being imported instead."""
    settings = {
        "ODIE_HOME": str(inst.home),
        "ODIE_SERVICE_LABEL": inst.label,
        "ODIE_PORT": str(inst.port),
        "ODIE_BRANCH": inst.branch,
        "ODIE_BIN_DIR": str(inst.bin_dir),
    }
    if str(inst.agents_dir) != str(Path.home() / "Library" / "LaunchAgents"):
        settings["ODIE_LAUNCH_AGENTS"] = str(inst.agents_dir)
    for name in PASSED_TO_SERVICE:
        if environ.get(name):
            settings[name] = environ[name]
    exports = " ".join(f"{name}={shlex.quote(value)}" for name, value in settings.items())
    cleared = " ".join(["ODIE_LAUNCH_AGENTS", "ODIE_VOICE_PORT", "ODIE_EMBED_PORT", "ODIE_PUBLIC_URL", "ODIE_DATA_DIR", "ODIE_CONFIG_DIR",
                        *PASSED_TO_SERVICE])
    return (
        "#!/bin/sh\n"
        f"{COMMAND_MARK}: it runs odie/cli.py from Odie's own copy, for the Odie in {inst.home}.\n"
        f"unset {cleared}\n"
        f"export {exports}\n"
        f"exec {shlex.quote(str(inst.python))} -P -m odie.cli \"$@\"\n"
    )


def cmd_write_command(inst: Install, environ: Mapping[str, str]) -> int:
    if inst.command.exists() and not is_our_command(inst.command):
        print(f"{inst.command} exists and isn't Odie's: move it away first.")
        return 1
    inst.bin_dir.mkdir(parents=True, exist_ok=True)
    inst.command.write_text(command_file_text(inst, environ))
    inst.command.chmod(0o755)
    return 0


# ── odie serve (what launchd and scripts/start.sh run) ──

def serve_environment(inst: Install, environ: Mapping[str, str], runner: Runner) -> dict[str, str]:
    """The settings Odie starts with, shared by the service and scripts/start.sh: its home, its port, its voice
    worker's port (port + 771 unless set), and the phone's address when `tailscale serve` points at this port (unless
    ODIE_PUBLIC_URL is already set), so QR codes and links point at the phone's address."""
    env = {"ODIE_HOME": str(inst.home), "ODIE_PORT": str(inst.port)}
    if not environ.get("ODIE_VOICE_PORT"):
        env["ODIE_VOICE_PORT"] = str(inst.voice_port)
    if not environ.get("ODIE_EMBED_PORT"):
        env["ODIE_EMBED_PORT"] = str(inst.embed_port)
    if not environ.get("ODIE_PUBLIC_URL"):
        phone = tailscale_phone_address(inst.port, runner)
        if phone:
            env["ODIE_PUBLIC_URL"] = phone
    return env


def open_setup_link_when_written(link_file: Path, runner: Runner, tries: int = 60) -> bool:
    """While nothing is paired, Odie writes a one-time setup link at startup; this opens it in this Mac's browser.
    Looks once a second for up to a minute."""
    for _ in range(tries):
        if link_file.exists() and link_file.stat().st_size > 0:
            print("Pairing this Mac's browser… (another computer, or over SSH? run: odie pair)", flush=True)
            runner.run(["open", link_file.read_text().strip()], timeout=10)
            return True
        runner.sleep(1)
    return False


def cmd_serve(inst: Install, runner: Runner) -> int:
    # 1. The environment Odie runs with.
    os.environ.update(serve_environment(inst, os.environ, runner))
    # 2. Say where it is.
    where = f"Odie: {inst.local_url}"
    phone = os.environ.get("ODIE_PUBLIC_URL", "")
    if phone:
        where += f"  ·  phone: {phone}"
    if inst.voice:
        where += f"  ·  voice worker: port {os.environ['ODIE_VOICE_PORT']}"
    else:
        where += "  ·  voice worker: off"
    print(where, flush=True)
    # 3. Pairing: a setup link left from an earlier start is stale, so it goes; this start's one opens in the browser.
    link_file = inst.home / "setup-link"
    link_file.unlink(missing_ok=True)
    threading.Thread(target=open_setup_link_when_written, args=(link_file, runner), daemon=True).start()
    # 4. Odie itself, in the foreground.
    import uvicorn
    uvicorn.run("odie.app.main:create_app", factory=True, host="127.0.0.1", port=inst.port, log_level="info")
    return 0


# ── the command line ──

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="odie", description="Run and update the Odie on this Mac.")
    sub = p.add_subparsers(dest="command", metavar="command")
    sub.add_parser("start", help="start Odie in the background (and at every login from now on)")
    sub.add_parser("stop", help="stop it (it stays stopped until odie start, even after a reboot)")
    sub.add_parser("restart", help="stop + start")
    sub.add_parser("status", help="running or not, version, address, health, which model")
    sub.add_parser("pair", help="a one-time code to pair a new device (over SSH, or another computer)")
    logs = sub.add_parser("logs", help="follow the server log (-e errors only, -n 200 the last 200 lines)")
    logs.add_argument("-n", type=int, dest="lines", help="show the last N lines and stop (add -f to keep following)")
    logs.add_argument("-e", action="store_true", dest="errors_only", help="only warnings, errors and tracebacks")
    logs.add_argument("-f", action="store_true", dest="follow", help="keep following after -n")
    sub.add_parser("open", help="open Odie in the browser")
    upd = sub.add_parser("update", help="move to the newest version; goes back by itself if anything fails")
    upd.add_argument("--rollback", action="store_true", help="go back to the version before the last update")
    upd.add_argument("--force", action="store_true", help="rebuild and restart even when already up to date")
    sub.add_parser("doctor", help="check everything Odie needs and say how to fix what's wrong")
    uni = sub.add_parser("uninstall", help="remove the service, the command and the app copy (asks about data)")
    uni.add_argument("--yes", action="store_true", help="remove the app and service without asking")
    data = uni.add_mutually_exclusive_group()
    data.add_argument("--delete-data", action="store_true", help="also delete the data, without asking")
    data.add_argument("--keep-data", action="store_true", help="keep the data, without asking")
    sub.add_parser("serve", help="run Odie in the foreground (what the service runs)")
    sub.add_parser("write-command", help="write the odie command file (scripts/install.sh runs this)")
    return p


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None, runner: Runner | None = None) -> int:
    if environ is None:
        os.environ["PATH"] = tool_path(os.environ.get("PATH", ""))
        environ = os.environ
    runner = runner or Runner()
    args = parser().parse_args(argv)
    inst = install_from(environ)
    if args.command == "start":
        return cmd_start(inst, runner, environ)
    if args.command == "stop":
        return cmd_stop(inst, runner)
    if args.command == "restart":
        return cmd_restart(inst, runner, environ)
    if args.command == "status":
        return cmd_status(inst, runner)
    if args.command == "pair":
        return cmd_pair(inst, runner, environ)
    if args.command == "logs":
        return cmd_logs(inst, runner, args.lines, args.errors_only, args.follow)
    if args.command == "open":
        return cmd_open(inst, runner)
    if args.command == "update":
        return cmd_update(inst, runner, force=args.force, rollback=args.rollback)
    if args.command == "doctor":
        return cmd_doctor(inst, runner)
    if args.command == "uninstall":
        remove_app = None  # None: ask
        if args.yes:
            remove_app = True
        delete_data = None
        if args.delete_data:
            delete_data = True
        if args.keep_data:
            delete_data = False
        return cmd_uninstall(inst, runner, remove_app, delete_data)
    if args.command == "serve":
        return cmd_serve(inst, runner)
    if args.command == "write-command":
        return cmd_write_command(inst, environ)
    parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
