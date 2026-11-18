"""The sandbox a Worker's commands and a pull request's tests run in (security review, 18 Nov 2026): macOS's
`sandbox-exec` with a profile written here. Text rules read the command line; a script the Worker wrote and then ran is
its own code, which no text rule reads. The sandbox holds whatever the code is:

  - reads: everything, except the secret places (secret_places: Odie's home, ~/.ssh, ~/.config/gh, ~/.gnupg, ~/.aws,
    ~/.netrc, the Keychains, iCloud Drive and the like) - but the job's own folder, even when it sits inside Odie's home;
  - writes: only the job's own folder (its temp folder is inside it: TMPDIR), the package caches a test needs (uv, pip,
    npm, ~/.cache, ~/Library/Caches), and /dev's null and terminals. Not $HOME, not /tmp, not Odie;
  - network: open (package installs, web reads), or closed altogether for a tainted job (offline=True).
So `rm -rf ~`, editing Odie's code or database, planting a test recipe, reading a key: refused by the kernel, whatever
script did it. What it doesn't stop: reading his ordinary files (a Worker may read ~/Downloads), and talking to the
network when the job isn't tainted."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
# Under the user's home: what no Worker and no test may read.
SECRET_HOME_PLACES = (".odie", ".ssh", ".config/gh", ".gnupg", ".aws", ".azure", ".config/gcloud", ".kube", ".docker",
                      ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".config/git/credentials", ".password-store",
                      ".zsh_history", ".bash_history", "Library/Keychains", "Library/Mobile Documents",
                      "Library/Cookies", "Library/Application Support/Google/Chrome")
CACHE_HOME_PLACES = (".cache", ".npm", "Library/Caches", ".local/share/uv")
KEPT_ENV = ("USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "TERM")


def available() -> bool:
    """Whether this computer has the sandbox: a Mac with /usr/bin/sandbox-exec -> True; anything else -> False (then
    Workers run no commands at all: odie.workers.shell says so)."""
    return sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)


def secret_places(home: Path | None = None) -> list[str]:
    """The places no Worker command and no test may read: SECRET_HOME_PLACES under the home, and Odie's own folders
    wherever they are (its home, data and settings: ODIE_HOME may move them)."""
    if home is None:
        home = Path.home()
    places = [str(home / p) for p in SECRET_HOME_PLACES]
    from odie import config
    for folder in (config.settings.data_dir, config.settings.config_dir, os.environ.get("ODIE_HOME")):
        if folder:
            places.append(str(Path(folder).expanduser()))
    return list(dict.fromkeys(places))


def cache_places(home: Path | None = None) -> list[str]:
    if home is None:
        home = Path.home()
    return [str(home / p) for p in CACHE_HOME_PLACES]


def _quoted(path: str) -> str:
    """A path as a profile string: "/a/b" -> "\\"/a/b\\""; a quote or a backslash in it is escaped."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _subpaths(paths: list[str]) -> str:
    return " ".join(f"(subpath {_quoted(p)})" for p in paths)


def profile(folder: Path, secrets: list[str] | None = None, offline: bool = False) -> str:
    """The profile for one job: secrets unreadable, its folder readable (it may sit inside a secret place), writes only
    in its folder, the caches and temp, the network closed when offline. Later rules win over earlier ones."""
    if secrets is None:
        secrets = secret_places()
    job = str(Path(folder).resolve())
    lines = ["(version 1)", "(allow default)"]
    if secrets:
        lines.append(f"(deny file-read* {_subpaths(secrets)})")
    lines.append(f"(allow file-read* (subpath {_quoted(job)}))")
    lines.append("(deny file-write*)")
    writable = [job, *cache_places()]
    lines.append(f"(allow file-write* {_subpaths(writable)} (literal \"/dev/null\") (literal \"/dev/tty\") "
                 "(literal \"/dev/dtracehelper\") (regex #\"^/dev/fd/\") (regex #\"^/dev/ttys\"))")
    if offline:
        lines.append("(deny network*)")
    return "\n".join(lines)


def command(argv: list[str], folder: Path, secrets: list[str] | None = None, offline: bool = False) -> list[str]:
    """argv run inside the job's sandbox: ["/usr/bin/sandbox-exec", "-p", <profile>, *argv]."""
    return [SANDBOX_EXEC, "-p", profile(folder, secrets, offline), *argv]


def env(folder: Path, home: Path | None = None) -> dict[str, str]:
    """The environment a sandboxed command gets: the user's name and language, a fixed PATH, temp inside the job's
    folder, CI=1, and the package caches where they are. HOME is the user's for a Worker (it may read his ordinary
    files); a test passes a throwaway one inside its folder. Nothing else: no GH_TOKEN, no API keys, no SSH agent."""
    from odie.agent.tools.shell import SHELL_PATH
    out = {name: os.environ[name] for name in KEPT_ENV if name in os.environ}
    real_home = Path.home()
    tmp = Path(folder) / ".tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    out.update(PATH=SHELL_PATH, HOME=str(home or real_home), TMPDIR=str(tmp), CI="1", GIT_TERMINAL_PROMPT="0",
               UV_CACHE_DIR=str(real_home / ".cache" / "uv"), UV_PYTHON_INSTALL_DIR=str(real_home / ".local/share/uv/python"),
               PIP_CACHE_DIR=str(real_home / "Library/Caches/pip"), npm_config_cache=str(real_home / ".npm"))
    return out
