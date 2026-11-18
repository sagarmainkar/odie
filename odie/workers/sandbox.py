"""The sandbox a Worker's commands and a pull request's tests run in (security reviews, 18-19 Nov 2026): macOS's
`sandbox-exec` with a DEFAULT-DENY profile written here. Text rules read the command line; a script the Worker wrote
and then ran is its own code, which no text rule reads. The sandbox holds whatever the code is. Allowed, and nothing
else:

  - reads: the system (/System, /usr, /bin, /sbin, /Library, /private/etc, /private/var/db, /private/var/select, /dev),
    Homebrew and /usr/local, the toolchains under the home (TOOLCHAINS: the uv-managed Pythons, ~/.local/bin, Rust's),
    read-only; the job's own folder; and any folder the owner named for this job (read_dirs), read-only. Nothing else
    under the home: no keys, no app tokens, no Documents, not Odie. File metadata (a path's existence and size) stays
    readable everywhere, which tools need to find their way; a folder's listing and a file's contents do not;
  - writes: the job's own folder only (its HOME, temp and package caches live inside it), and /dev's null and
    terminals. Not the home, not /tmp, not a cache, not a toolchain;
  - processes: fork and exec, except EXEC_DENIED (open, osascript, launchctl, at, crontab, ssh, security, defaults,
    tmux, screen, sudo); signals only to its own; system services (mach-lookup) only MACH_ALLOWED (name lookup,
    network settings, certificate trust, user names, logging): LaunchServices, AppleEvents, the pasteboard, the
    Keychain and every other app are unreachable, so nothing it starts can run outside the sandbox;
  - network: none for a Worker; for a pull request's test, the internet (packages install) but never this computer:
    no localhost (Odie, Ollama, other agents), no unix sockets (tmux, the SSH agent) but the DNS resolver's.
What it doesn't stop: reading file metadata, and, for a test, talking to the internet (it can read nothing secret)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
SYSTEM_READS = ("/System", "/usr", "/bin", "/sbin", "/Library", "/private/etc", "/private/var/db",
                "/private/var/select", "/dev", "/opt/homebrew", "/usr/local")
TOOLCHAINS = (".local/share/uv/python", ".local/bin", ".cargo/bin", ".rustup/toolchains")  # under the home, read-only
EXEC_DENIED = ("/usr/bin/open", "/usr/bin/osascript", "/bin/launchctl", "/usr/bin/at", "/usr/bin/crontab",
               "/usr/bin/ssh", "/usr/bin/scp", "/usr/bin/sftp", "/usr/bin/security", "/usr/bin/defaults",
               "/usr/bin/pbcopy", "/usr/bin/pbpaste", "/usr/bin/sudo", "/usr/bin/screen", "/opt/homebrew/bin/tmux",
               "/usr/local/bin/tmux", "/opt/homebrew/bin/screen")
MACH_ALLOWED = ("com.apple.dnssd.service", "com.apple.SystemConfiguration.configd", "com.apple.trustd",
                "com.apple.trustd.agent", "com.apple.ocspd", "com.apple.system.opendirectoryd.libinfo",
                "com.apple.system.notification_center", "com.apple.logd", "com.apple.system.logger")
DNS_SOCKET = "/private/var/run/mDNSResponder"
KEPT_ENV = ("USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "TERM")
NONE = "none"
INTERNET = "internet"


def available() -> bool:
    """Whether this computer has the sandbox: a Mac with /usr/bin/sandbox-exec -> True; anything else -> False (then
    Workers run no commands and pull requests aren't tested: odie.workers.shell, odie.loops.pr_test)."""
    return sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)


def _quoted(path: str) -> str:
    """A path as a profile string: /a/b -> "/a/b"; a quote or a backslash in it is escaped."""
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _subpaths(paths) -> str:
    return " ".join(f"(subpath {_quoted(p)})" for p in paths)


def toolchain_reads(home: Path | None = None) -> list[str]:
    """The toolchain folders under the home that exist here, read-only."""
    if home is None:
        home = Path.home()
    return [str(home / p) for p in TOOLCHAINS if (home / p).exists()]


def profile(folder: Path, read_dirs: list[str] | tuple = (), network: str = NONE, home: Path | None = None) -> str:
    """The default-deny profile for one job (this module's notes). folder: the job's own folder (read and write);
    read_dirs: folders the owner named for it (read-only); network: NONE (a Worker) or INTERNET (a pull request's
    test: the internet, never this computer). home: the user's home (tests pass a stand-in)."""
    job = str(Path(folder).resolve())
    reads = [*SYSTEM_READS, *toolchain_reads(home), job, *(str(Path(d).resolve()) for d in read_dirs)]
    mach = " ".join(f"(global-name {_quoted(m)})" for m in MACH_ALLOWED)
    denied_exec = " ".join(f"(literal {_quoted(p)})" for p in EXEC_DENIED)
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-fork)",
        "(allow process-exec)",
        f"(deny process-exec {denied_exec})",
        "(allow signal (target same-sandbox))",
        "(allow process-info* (target same-sandbox))",
        "(allow sysctl-read)",
        "(allow ipc-posix-sem)",
        "(allow ipc-posix-shm)",
        "(allow file-ioctl)",
        "(allow system-socket)",
        "(allow file-read-metadata)",
        '(allow file-read* (literal "/") (literal "/private") (literal "/private/var"))',
        f"(allow file-read* {_subpaths(reads)})",
        f"(allow file-write* (subpath {_quoted(job)}) (literal \"/dev/null\") (literal \"/dev/tty\") "
        "(literal \"/dev/dtracehelper\") (regex #\"^/dev/fd/\") (regex #\"^/dev/ttys\"))",
        f"(allow mach-lookup {mach})",
    ]
    if network == INTERNET:
        # A generic allow first: a deny after it holds (a deny after (remote ip "*:*") doesn't, tried 19 Nov).
        lines += ["(allow network-outbound)",
                  '(deny network-outbound (remote ip "localhost:*"))',
                  "(deny network-outbound (remote unix-socket))",
                  f"(allow network-outbound (literal {_quoted(DNS_SOCKET)}))"]
    return "\n".join(lines)


def command(argv: list[str], folder: Path, read_dirs: list[str] | tuple = (), network: str = NONE,
            home: Path | None = None) -> list[str]:
    """argv run inside the job's sandbox: ["/usr/bin/sandbox-exec", "-p", <profile>, *argv]."""
    return [SANDBOX_EXEC, "-p", profile(folder, read_dirs, network, home), *argv]


def env(folder: Path) -> dict[str, str]:
    """The environment a sandboxed command gets: the user's name and language, a fixed PATH, and HOME, temp and every
    package cache inside the job's own folder (HOME is not his: the sandbox couldn't read it anyway). Nothing else: no
    GH_TOKEN, no API keys, no SSH agent, no ODIE_* settings."""
    from odie.agent.tools.shell import SHELL_PATH
    out = {name: os.environ[name] for name in KEPT_ENV if name in os.environ}
    base = Path(folder)
    places = {"HOME": base / ".home", "TMPDIR": base / ".tmp", "XDG_CACHE_HOME": base / ".cache",
              "UV_CACHE_DIR": base / ".cache" / "uv", "PIP_CACHE_DIR": base / ".cache" / "pip",
              "npm_config_cache": base / ".cache" / "npm", "UV_PYTHON_INSTALL_DIR": base / ".cache" / "uv-python"}
    for name, place in places.items():
        place.mkdir(parents=True, exist_ok=True)
        out[name] = str(place)
    out.update(PATH=SHELL_PATH, CI="1", GIT_TERMINAL_PROMPT="0")
    return out


# ── finding what a job left running ──────────────────────────────────────────
# A process can leave its group (setsid), drop its environment (env -i) and leave the folder (chdir /). It can't leave
# its sandbox. macOS's sandbox_check tells, for any process of this user, whether its sandbox lets it read a path: a
# process of THIS job's sandbox may read the job's folder but not a folder beside it (Odie's own record of the job,
# which no sandbox may read); an unsandboxed process may read both; another job's, neither. Both must exist.

_CHECK = None


def _sandbox_check():
    """sandbox_check(pid, operation, type, path) through ctypes. Its path is a variadic argument, which on Apple
    silicon goes on the stack: five padding arguments fill the remaining registers, so the path lands there."""
    global _CHECK
    if _CHECK is None:
        import ctypes
        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                 *([ctypes.c_int64] * 5), ctypes.c_char_p)
        _CHECK = proto(("sandbox_check", lib))
    return _CHECK


_SANDBOXED = None


def sandboxed(pid: int) -> bool | None:
    """Whether a process runs in any sandbox at all (sandbox_check with no operation), or None when it can't tell."""
    global _SANDBOXED
    try:
        if _SANDBOXED is None:
            import ctypes
            lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int)
            _SANDBOXED = proto(("sandbox_check", lib))
        answer = _SANDBOXED(pid, None, 0)
    except Exception:  # noqa: BLE001
        return None
    if answer < 0:
        return None
    return answer == 1


def may_read(pid: int, path: str) -> bool | None:
    """Whether a process's sandbox lets it read this path (True/False), or None when the check can't be made."""
    try:
        check = _sandbox_check()
        answer = check(pid, b"file-read-data", 1 | 0x40000000, 0, 0, 0, 0, 0, str(path).encode())
    except Exception:  # noqa: BLE001 (no sandbox_check here: the caller falls back to process groups)
        return None
    if answer < 0:
        return None
    return answer == 0


def in_job_sandbox(pid: int, folder: Path, beside: Path) -> bool:
    """Whether a process runs in the sandbox of the job whose folder this is: it may read the folder and may not read
    `beside` (a folder next to it that no sandbox may read).
      a job's command, even after setsid, env -i and chdir / -> True
      Odie, the user's shell (unsandboxed: may read both)   -> False
      another job's command (may read neither)              -> False"""
    inside = may_read(pid, str(folder))
    outside = may_read(pid, str(beside))
    return inside is True and outside is False


def processes_in(folder: Path, beside: Path) -> list[int]:
    """Every process of this user running in the job's sandbox now (Odie itself never)."""
    import subprocess
    folder.mkdir(parents=True, exist_ok=True)  # both must exist for the check; a job may have removed its folder
    beside.mkdir(parents=True, exist_ok=True)
    listing = subprocess.run(["/bin/ps", "-axo", "pid=,uid="], capture_output=True, text=True).stdout
    mine = os.getuid()
    found = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        pid, uid = int(parts[0]), int(parts[1])
        if uid != mine or pid == os.getpid():
            continue
        if sandboxed(pid) is False:
            continue  # not in any sandbox: not the job's (cheap check first)
        if in_job_sandbox(pid, folder, beside):
            found.append(pid)
    return found
