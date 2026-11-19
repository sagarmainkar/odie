"""The sandbox a Worker's commands and a pull request's tests run in (security reviews, 18-19 Nov 2026): macOS's
`sandbox-exec` with a DEFAULT-DENY profile written here. Text rules read the command line; a script the Worker wrote
and then ran is its own code, which no text rule reads. The sandbox holds whatever the code is. Allowed, and nothing
else:

  - reads: the system (/System, /usr, /bin, /sbin, /Library, /private/etc, /private/var/db, /private/var/select, /dev),
    Homebrew and /usr/local, the Xcode app when it is the selected developer tools (developer_reads), the toolchains
    under the home (TOOLCHAINS: the uv-managed Pythons, ~/.local/bin, Rust's),
    read-only; the job's own folder; and any folder the owner named for this job (read_dirs), read-only. Nothing else
    under the home: no keys, no app tokens, no Documents, not Odie. File metadata (a path's existence and size) stays
    readable everywhere, which tools need to find their way; a folder's listing and a file's contents do not;
  - writes: the job's own folder only (its HOME, temp and package caches live inside it), and /dev's null and
    terminals. Not the home, not /tmp, not a cache, not a toolchain;
  - no shared memory and no SysV IPC; semaphores only under the job's own name prefix (Python's multiprocessing is
    steered there), so two jobs can't pass anything through them; no notification service;
  - processes: fork and exec, except EXEC_DENIED (open, osascript, launchctl, at, crontab, ssh, security, defaults,
    tmux, screen, sudo); signals only to its own; system services (mach-lookup) only MACH_ALLOWED (name lookup,
    network settings, certificate trust, user names, logging): LaunchServices, AppleEvents, the pasteboard, the
    Keychain and every other app are unreachable, so nothing it starts can run outside the sandbox;
  - network: none for a Worker that may read his folders or apps; for a Worker that can read nothing of his
    (odie.workers.shell.network_for) and for a pull request's test, the internet (packages install) but never this
    computer: no localhost (Odie, Ollama, other agents), no unix sockets (tmux, the SSH agent) but the DNS resolver's.
What it doesn't stop: reading file metadata, and, for a test, talking to the internet (it can read nothing secret)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
SYSTEM_READS = ("/System", "/usr", "/bin", "/sbin", "/Library", "/private/etc", "/private/var/db/timezone",
                "/private/var/select", "/dev", "/opt/homebrew", "/usr/local")  # not /private/var/db's system logs
# Files no named folder may ever show, wherever they sit below it (third review, 19 Nov 2026): anything hidden (a
# part starting with "." : .env, .git, .ssh) and the usual names of keys and secrets.
SECRET_NAME_PATTERNS = (r"(.*/)?\.", r"(.*/)?[^/]*\.(pem|key|p12|pfx|keystore|jks|ppk)$", r"(.*/)?id_[^/]*$",
                        r"(.*/)?secrets?\.[^/]*$", r"(.*/)?credentials[^/]*$", r"(.*/)?[^/]*\.kdbx$")
TOOLCHAINS = (".local/share/uv/python", ".local/bin", ".cargo/bin", ".rustup/toolchains")  # under the home, read-only
EXEC_DENIED = ("/usr/bin/open", "/usr/bin/osascript", "/bin/launchctl", "/usr/bin/at", "/usr/bin/crontab",
               "/usr/bin/ssh", "/usr/bin/scp", "/usr/bin/sftp", "/usr/bin/security", "/usr/bin/defaults",
               "/usr/bin/pbcopy", "/usr/bin/pbpaste", "/usr/bin/sudo", "/usr/bin/screen", "/opt/homebrew/bin/tmux",
               "/usr/local/bin/tmux", "/opt/homebrew/bin/screen", "/usr/sbin/lsof")
MACH_ALLOWED = ("com.apple.dnssd.service", "com.apple.SystemConfiguration.configd", "com.apple.trustd",
                "com.apple.trustd.agent", "com.apple.ocspd", "com.apple.system.opendirectoryd.libinfo",
                "com.apple.logd", "com.apple.system.logger")  # not notifyd: two jobs could signal through it
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


XCODE_LINK = "/private/var/db/xcode_select_link"  # where `xcode-select` keeps the selected developer folder


def xcode_developer() -> Path | None:
    """Xcode's Developer folder when Xcode is the selected developer tools, else None.
      selected: /Applications/Xcode.app/Contents/Developer -> that folder
      the Command Line Tools (/Library/Developer/CommandLineTools), nothing selected, or a folder that is no
      ….app/Contents/Developer -> None"""
    chosen = os.environ.get("DEVELOPER_DIR") or XCODE_LINK
    try:
        folder = Path(chosen).resolve(strict=True)
    except OSError:
        return None
    ends_as_developer = folder.parts[-2:] == ("Contents", "Developer")
    inside_an_app = folder.parent.parent.suffix == ".app"
    if not folder.is_dir() or not (ends_as_developer and inside_an_app):
        return None
    return folder


def developer_reads() -> list[str]:
    """What a job must read to use the developer tools when Xcode is the selected one: the Xcode app, read-only.
    /usr/bin/git, make, cc and python3 are small launchers that load the real tool and its libraries from inside the
    app (Contents/Developer and Contents/SharedFrameworks), so without this every job fails with "xcrun: error" or
    "Library not loaded". Xcode selected -> ["/Applications/Xcode.app"]; the Command Line Tools -> [] (they sit under
    /Library, which is readable already)."""
    developer = xcode_developer()
    if developer is None:
        return []
    return [str(developer.parents[1])]


def developer_path(path: str) -> str:
    """A PATH with Xcode's real tools ahead of /usr/bin's launchers when Xcode is the selected one, so git, make and
    python3 start directly and never ask the launcher to find them. Unchanged otherwise.
      Xcode selected, "/opt/homebrew/bin:/usr/bin:/bin" ->
        "/opt/homebrew/bin:<Developer>/usr/bin:<Developer>/Toolchains/XcodeDefault.xctoolchain/usr/bin:/usr/bin:/bin"
      the Command Line Tools -> the same PATH"""
    developer = xcode_developer()
    if developer is None:
        return path
    real = [developer / "usr" / "bin", developer / "Toolchains" / "XcodeDefault.xctoolchain" / "usr" / "bin"]
    ahead = [str(folder) for folder in real if folder.is_dir()]
    parts = path.split(":")
    at = len(parts)
    if "/usr/bin" in parts:
        at = parts.index("/usr/bin")
    return ":".join([*parts[:at], *ahead, *parts[at:]])


def developer_env() -> dict[str, str]:
    """DEVELOPER_DIR for a job when Xcode is the selected one, so a launcher that is still called (/usr/bin/cc by its
    full path) knows where to look without reading the selection. Else nothing."""
    developer = xcode_developer()
    if developer is None:
        return {}
    return {"DEVELOPER_DIR": str(developer)}


def toolchain_reads(home: Path | None = None) -> list[str]:
    """The toolchain folders under the home that exist here, read-only."""
    if home is None:
        home = Path.home()
    return [str(home / p) for p in TOOLCHAINS if (home / p).exists()]


def regex_quoted(path: str) -> str:
    """A path inside a profile regex: every character that means something in a regex is escaped."""
    return "".join("\\" + c if c in ".^$*+?()[]{}|\\" else c for c in path)


def odie_places() -> list[str]:
    """Odie's own folders wherever they are (its home, data and settings): never readable, whatever is named."""
    from odie import config
    places = [config.settings.data_dir, config.settings.config_dir, os.environ.get("ODIE_HOME")]
    return [str(Path(p).expanduser().resolve()) for p in places if p]


def denials_after_named(read_dirs, home: Path) -> list[str]:
    """What no named folder can uncover, written after the named folders' allows (a later rule wins): below each named
    folder, hidden files and folders and key or secret file names; and the home's own hidden places, its Library and
    Odie's folders. The kernel matches the real path on disk, so a named folder spelled in another case
    (~/library/…) still meets these."""
    out = []
    for d in read_dirs:
        root = regex_quoted(str(Path(d).resolve()))
        patterns = " ".join(f'(regex #"^{root}/{p}")' for p in SECRET_NAME_PATTERNS)
        out.append(f"(deny file-read* {patterns})")
    home_root = regex_quoted(str(home.resolve()))
    out.append(f'(deny file-read* (regex #"^{home_root}/\\.") (subpath {_quoted(str(home.resolve() / "Library"))}) '
               f"{_subpaths(odie_places())})")
    return out


def profile(folder: Path, read_dirs: list[str] | tuple = (), network: str = NONE, home: Path | None = None) -> str:
    """The default-deny profile for one job (this module's notes). folder: the job's own folder (read and write);
    read_dirs: folders the owner named for it (read-only, never their hidden or secret files); network: NONE (a Worker)
    or INTERNET (a pull request's test: the internet, never this computer). home: the user's home (tests pass a
    stand-in). Order matters, a later rule winning: the system and the named folders, then what nothing may uncover,
    then the toolchains (hidden folders under the home) and the job's own folder (inside Odie's) again."""
    if home is None:
        home = Path.home()
    job = str(Path(folder).resolve())
    reads = [*SYSTEM_READS, *developer_reads(), *(str(Path(d).resolve()) for d in read_dirs)]
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
        # No shared memory, no SysV IPC: two jobs could pass his data through them (fourth review). Semaphores only
        # under this job's own name prefix (Python's multiprocessing is steered there: sitecustomize below).
        "(deny ipc-sysv*)",
        f'(allow ipc-posix-sem (ipc-posix-name-prefix "{semaphore_prefix(folder)}-"))',
        "(allow file-ioctl)",
        "(allow system-socket)",
        "(allow file-read-metadata)",
        f'(allow file-read* (literal "/") (literal "/private") (literal "/private/var") (literal {_quoted(XCODE_LINK)}))',
        f"(allow file-read* {_subpaths(reads)})",
        *denials_after_named(read_dirs, home),
        f"(allow file-read* {_subpaths([*toolchain_reads(home), job])})",
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


def semaphore_prefix(folder: Path) -> str:
    """The job's own prefix for POSIX semaphore names: "/mp-" and 8 characters from its folder, so no two jobs share
    one (and Python's names, "/mp-<8>-<8>", stay inside macOS's 31 characters)."""
    import hashlib
    digest = hashlib.sha256(str(Path(folder).resolve()).encode()).hexdigest()[:8]
    return f"/mp-{digest}"


SITECUSTOMIZE = """try:
    import multiprocessing.process as _odie_process
    _odie_process.current_process()._config["semprefix"] = {prefix!r}
except Exception:
    pass
"""


def python_hook(folder: Path) -> Path:
    """A folder in the job holding a sitecustomize.py that steers Python's multiprocessing semaphore names to the
    job's own prefix (the only ones its sandbox allows); put on PYTHONPATH. A job that changes it only breaks its own
    multiprocessing: the profile allows no other prefix."""
    hook = Path(folder) / ".odie-python"
    hook.mkdir(parents=True, exist_ok=True)
    (hook / "sitecustomize.py").write_text(SITECUSTOMIZE.format(prefix=semaphore_prefix(folder)))
    return hook


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
              "npm_config_cache": base / ".cache" / "npm", "UV_PYTHON_INSTALL_DIR": base / ".cache" / "uv-python",
              "CARGO_HOME": base / ".cache" / "cargo", "GOPATH": base / ".cache" / "go",
              "GOCACHE": base / ".cache" / "go-build", "GOMODCACHE": base / ".cache" / "go" / "mod",
              "BUNDLE_USER_HOME": base / ".cache" / "bundle"}  # named, so no tool looks for its own under his home
    for name, place in places.items():
        place.mkdir(parents=True, exist_ok=True)
        out[name] = str(place)
    out.update(PATH=developer_path(SHELL_PATH), CI="1", GIT_TERMINAL_PROMPT="0")
    out["PYTHONPATH"] = str(python_hook(base))
    out.update(developer_env())
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
    return [pid for pid, _ in groups_in(folder, beside)]


_LISTPIDS = None


def my_pids() -> list[int]:
    """This user's processes, listed in-process (libproc's proc_listpids by uid): a fraction of a millisecond, so a
    process that keeps re-forking is still alive when it is checked. `ps` (a fork and an exec) is the fallback."""
    global _LISTPIDS
    try:
        import ctypes
        if _LISTPIDS is None:
            lib = ctypes.CDLL("/usr/lib/libproc.dylib")
            _LISTPIDS = lib.proc_listpids
            _LISTPIDS.restype = ctypes.c_int
            _LISTPIDS.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        size = 4096
        buffer = (ctypes.c_int * size)()
        used = _LISTPIDS(4, os.getuid(), buffer, ctypes.sizeof(buffer))  # 4: PROC_UID_ONLY
        if used <= 0:
            raise OSError("proc_listpids gave nothing")
        return [pid for pid in buffer[: used // ctypes.sizeof(ctypes.c_int)] if pid > 0]
    except Exception:  # noqa: BLE001
        import subprocess
        listing = subprocess.run(["/bin/ps", "-axo", "pid=,uid="], capture_output=True, text=True).stdout
        mine = str(os.getuid())
        return [int(line.split()[0]) for line in listing.splitlines() if len(line.split()) == 2 and line.split()[1] == mine]


def groups_in(folder: Path, beside: Path, others: set[int] | None = None) -> list[tuple[int, int]]:
    """Every process of this user running in the job's sandbox now, with its process group: [(pid, pgid)]. others:
    pids already found not to be the job's in this sweep (skipped, and grown here), so a repeated look checks only new
    processes, in microseconds: a chain that re-forks and moves to a new session every hop is still caught alive."""
    folder.mkdir(parents=True, exist_ok=True)  # both must exist for the check; a job may have removed its folder
    beside.mkdir(parents=True, exist_ok=True)
    if others is None:
        others = set()
    found = []
    me = os.getpid()
    for pid in sorted(my_pids(), reverse=True):  # newest first: a re-forking chain's head has the highest pid
        if pid == me or pid in others:
            continue
        if sandboxed(pid) is False or not in_job_sandbox(pid, folder, beside):
            others.add(pid)
            continue
        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError):
            continue
        found.append((pid, pgid))
    return found
