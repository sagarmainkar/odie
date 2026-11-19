"""A Worker's clone_repo (simpler Workers, 19 Nov 2026): "try this repo" needs a copy of someone else's code, and a
Worker's shell has no network. So code clones it, inside the job's own sandbox (odie.workers.sandbox, unchanged) in
the network mode a pull request's test already uses: the internet, never this computer (no localhost, no unix
sockets), writes only in the job's folder. Only git runs there, never the repo's code, and git is locked down:
  - only a public https address (no sign-in in it, nothing on this computer or the home network: web_fetch's check);
  - only the https protocol, no redirects (an address can't bounce to the home network), no credential helper (his
    sign-ins never come along), hooks and the file-system monitor off, no submodules, depth 1;
  - no settings file of anyone's: not his, and not one the Worker wrote into its own home (GIT_CONFIG_GLOBAL is
    /dev/null, GIT_CONFIG_NOSYSTEM), so the Worker can't make git run a command of its choosing with the internet.
Whatever git started is killed when it returns (odie.workers.shell.sweep), as after any command of the job's."""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from google.adk.tools import FunctionTool

from odie.workers import sandbox

CLONE_SECONDS = 300
OUTPUT_CAP = 2000
GIT_LOCKED = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
              "-c", "protocol.https.allow=always", "-c", "http.followRedirects=false", "-c", "credential.helper=",
              "-c", "submodule.recurse=false")


async def problem_with(url: str, resolve) -> str | None:
    """Why this address may not be cloned, or None when it may: a public https address, with no sign-in in it.
      "https://github.com/example/app.git" -> None
      "http://…", "ssh://git@…", "git@github.com:x/y" -> "only https addresses…"
      "https://user:token@github.com/x/y"            -> "…no sign-in…"
      "https://127.0.0.1/x/y", a home-network name   -> "…this computer or the local network…\""""
    from odie.agent.tools.web import public_url
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "only https addresses of public repos can be cloned"
    if parsed.username or parsed.password:
        return "an address with a sign-in in it is never cloned (only public repos)"
    problem = await public_url(url, resolve)
    if problem:
        return problem.replace("web_fetch never reads", "a Worker never clones")
    return None


def name_for(url: str, folder: Path) -> str:
    """The folder a clone goes to in the job's folder, from the address's last part, made safe and never one that is
    there already: ".../Hello-World.git" -> "Hello-World"; again -> "Hello-World-2"; ".../.hidden.git" -> "hidden";
    no name in it -> "repo"."""
    last = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if last.endswith(".git"):
        last = last[: -len(".git")]
    name = re.sub(r"[^A-Za-z0-9._-]", "-", last).lstrip(".-")[:80]
    if not name:
        name = "repo"
    candidate = name
    n = 2
    while (folder / candidate).exists() or (folder / candidate).is_symlink():
        candidate = f"{name}-{n}"
        n += 1
    return candidate


def git_path() -> str:
    from odie.agent.tools.shell import SHELL_PATH
    found = shutil.which("git", path=SHELL_PATH)
    if found:
        return found
    return "/usr/bin/git"


def clone_argv(url: str, dest: Path, folder: Path) -> list[str]:
    """The clone, as run: git locked down (GIT_LOCKED), inside the job's sandbox with the internet."""
    git = [git_path(), *GIT_LOCKED, "clone", "--depth", "1", "--single-branch", "--no-recurse-submodules", "--quiet",
           "--", url, str(dest)]
    return sandbox.command(git, folder, network=sandbox.INTERNET)


def clone_env(folder: Path) -> dict[str, str]:
    """The job's own environment (sandbox.env) and no git settings file of anyone's."""
    env = sandbox.env(folder)
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return env


def make_clone_tool(job) -> FunctionTool:
    from odie.agent.tools.web import resolve_host

    async def clone_repo(url: str) -> dict:
        """Clone a public git repo (an https address) into your folder, at its latest commit, without its history. Returns the folder it went to. Use this, not git in the shell: the shell has no network."""
        if not sandbox.available():
            return {"error": "Not run: this computer has no sandbox for Workers."}
        problem = await problem_with(url, resolve_host)
        if problem:
            return {"error": f"Not cloned: {problem}."}
        from odie.workers import shell
        name = name_for(url, job.folder)
        dest = job.folder / name
        shell._FOLDERS[job.id] = job.folder  # so a Stop sweeps it too
        try:
            argv = clone_argv(url, dest, job.folder)
            proc = await asyncio.create_subprocess_exec(*argv, cwd=str(job.folder), env=clone_env(job.folder),
                                                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return {"error": f"Could not run git: {e}"}
        shell._GROUPS.setdefault(job.id, set()).add(proc.pid)
        try:
            output, _ = await asyncio.wait_for(proc.communicate(), CLONE_SECONDS)
        except TimeoutError:
            return {"error": f"Not cloned: it took more than {CLONE_SECONDS // 60} minutes."}
        finally:
            shell._kill_group(proc.pid)
            shell._GROUPS.get(job.id, set()).discard(proc.pid)
            shell.sweep(job.folder)
        if proc.returncode != 0:
            said = output.decode(errors="replace").strip()[-OUTPUT_CAP:]
            return {"error": f"Not cloned (git exit {proc.returncode}): {said}"}
        return {"cloned": name, "path": str(dest)}

    return FunctionTool(clone_repo)
