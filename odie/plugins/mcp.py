"""MCP servers the user adds in ~/.odie/mcp.json (standard mcpServers format). Each is on demand by default
(a synthetic skill whose tools switch on when loaded); its tools ask for a tap, unless the user switched "Reading
doesn't need a tap" on for that server and the tool's name says it reads (asks)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams, StreamableHTTPConnectionParams
from google.adk.skills.models import Frontmatter, Skill
from mcp import StdioServerParameters

from odie import config
from odie.approvals_mode import asks_by_name, name_words
from odie.setup.keys import KEY_PREFIX, SECRET_NAME, secret_part

MAX_EVENT_BYTES = 32 * 1024 * 1024


def _allow_big_events() -> None:
    """The MCP client reads each server event with httpx2's 1 MB limit, and a bigger one (Zapier's Gmail search sends
    whole emails) fails as "SSE stream ended without a response". Odie reads up to 32 MB; the plugin then cuts what the
    model sees (APP_RESULT_LIMIT)."""
    import httpx2
    from mcp.client import streamable_http

    class EventSource(httpx2.EventSource):
        def __init__(self, response, max_event_size: int | None = MAX_EVENT_BYTES) -> None:
            super().__init__(response, max_event_size=max_event_size)
    streamable_http.EventSource = EventSource


_allow_big_events()


def _hint(tool, snake: str, camel: str) -> bool:
    """Does the MCP server mark this tool with that hint, under either spelling?
    Example: annotations readOnlyHint=True -> _hint(tool, "read_only_hint", "readOnlyHint") is True;
    a tool with no annotations -> False."""
    raw = getattr(tool, "raw_mcp_tool", None)
    annotations = getattr(raw, "annotations", None)
    if annotations is None:
        return False
    snake_value = getattr(annotations, snake, None)
    camel_value = getattr(annotations, camel, None)
    return bool(snake_value or camel_value)


def is_read_only(tool) -> bool:
    return _hint(tool, "read_only_hint", "readOnlyHint")


def is_destructive(tool) -> bool:
    return _hint(tool, "destructive_hint", "destructiveHint")


_READ_WORDS = frozenset({"find", "get", "list", "search", "fetch"})
_CHANGE_WORDS = frozenset("""send create update delete remove add post put patch write set execute run reply forward move archive
    cancel schedule invite upload draft modify edit insert trash mark star label apply approve pay transfer book submit start
    stop enable disable share publish import export call trigger invoke do perform manage replace clear merge append assign
    sync copy rename reset revoke resolve close complete acknowledge ack dismiss snooze unarchive subscribe unsubscribe register
    save notify purchase buy refund charge kill terminate destroy drop purge wipe truncate resend retry reopen
    reassign toggle lock unlock pin unpin mute block follow like react vote sign accept reject decline confirm grant deny redeem
    claim release reserve attach detach unlink untag clone fork commit revert rollback restore
    migrate connect disconnect login logout""".split())
_JOINS = frozenset({"and", "or", "then", "plus"})  # two actions in one tool: never a pure read
# Words that are mostly nouns (email, message, record, order, link, tag, comment) aren't change words: find_email reads.


def is_read_name(name: str) -> bool:
    """A tool whose name says it reads (find, get, list, search, fetch) and says nothing about changing anything:
    gmail_find_email and GMAIL_FETCH_EMAILS are reads; get_or_create_contact and COMPOSIO_MULTI_EXECUTE_TOOL aren't."""
    words = name_words(name)
    return bool(words & _READ_WORDS) and not words & (_CHANGE_WORDS | _JOINS)


def asks(tool: dict, reads_free: bool, smart: bool = False) -> bool:
    """Whether a tool ({name, read_only, destructive}) needs the user's tap.
    Careful (smart off, today's rule): only the user's own switch frees a tool. With the server's "Reading doesn't need
    a tap" switch (reads_free) on, a tool whose name says it reads (is_read_name) and that the server doesn't mark
    destructive runs without a tap; everything else asks. The server's readOnlyHint on its own frees nothing: it's the
    server's word about itself, and a server (or whoever controls it) can write it on any tool.
    Smart: a tool runs unless its name has an ask-word (send, pay, delete, execute ...: approvals_mode.asks_by_name) or
    the server marks it destructive. The reads_free switch no longer matters, and the server's read-only hint still frees
    nothing.
    Examples, Careful: write_note marked read-only, switch off -> True (asks); list_items, switch off -> True; list_items,
    switch on -> False; delete_thread marked read-only, switch on -> True (its name says it changes something);
    fetch_report marked destructive, switch on -> True.
    Examples, Smart: GMAIL_SEND_EMAIL -> True; GMAIL_FETCH_EMAILS -> False; write_note -> False; delete_note -> True;
    list_items, switch off -> False; fetch_report marked destructive -> True; COMPOSIO_MULTI_EXECUTE_TOOL -> True."""
    name = str(tool.get("name", ""))
    marked_destructive = bool(tool.get("destructive"))
    if smart:
        return asks_by_name(name) or marked_destructive
    if not reads_free:
        return True
    name_reads = is_read_name(name)
    return not (name_reads and not marked_destructive)


SHELLS = frozenset({"sh", "bash", "zsh", "dash", "fish", "ksh", "csh", "tcsh", "cmd", "cmd.exe", "powershell", "pwsh"})
# Flags that take code or a file to load before the program's own: python -c, node -e/-p/--eval/--print/--require/
# --import, ruby -e, perl -e/-E/-M, osascript -e, deno eval. Matched as a whole word, joined (-cCODE, --eval=1) or in a
# cluster (-Sc, -pe).
INLINE_CODE_FLAGS = frozenset({"-c", "-e", "-p", "--eval", "--print", "-r", "--require", "--import", "--exec", "-x", "-E", "-M"})
INLINE_CODE_WORDS = frozenset({"eval"})  # deno eval, bun eval: a subcommand that runs text
INTERPRETERS = frozenset({"python", "python3", "node", "nodejs", "ruby", "perl", "deno", "bun", "osascript", "php", "lua"})
# Programs that only run the program after them (with their own options first): the next word is the real command.
WRAPPERS = frozenset({"env", "nohup", "nice", "time", "caffeinate", "xargs", "script", "busybox", "stdbuf", "timeout",
                      "command", "exec", "ionice", "setsid", "doas", "sudo"})
# Variables that make a program run code from somewhere else before its own: a spec's env may not set them.
HOOK_VARS = frozenset({"NODE_OPTIONS", "PYTHONSTARTUP", "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "LD_PRELOAD", "LD_LIBRARY_PATH",
                       "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "BASH_ENV", "ENV", "ZDOTDIR", "PERL5OPT", "PERL5LIB", "PERLLIB",
                       "PERL5DB", "RUBYOPT", "RUBYLIB", "GEM_PATH", "NODE_PATH", "PATH"})
_VERSIONED = re.compile(r"^([a-z][a-z0-9_+]*?)(?:[-.]?\d[\d.]*)?$")  # python3.12, zsh-5.9, node22 -> python, zsh, node
_SHORT_CLUSTER = re.compile(r"^-[A-Za-z]{1,3}$")  # -Sc, -pe: a few one-letter flags together


def program_name(command: str) -> str:
    """The program a command names, as the lists know it: the last path part, lower-case, spaces and a version
    dropped, a symlink followed.
      "/bin/sh" -> "sh";  " sh" -> "sh";  "python3.12" -> "python3";  "zsh-5.9" -> "zsh";  a link to /bin/sh -> sh"""
    text = command.strip()
    if "/" in text:
        try:
            text = os.path.realpath(text)
        except OSError:
            pass
    name = text.rsplit("/", 1)[-1].lower()
    m = _VERSIONED.match(name)
    if m and m.group(1) in SHELLS | INTERPRETERS:
        return m.group(1)
    if name.startswith("python3"):
        return "python3"
    return name


def runs_code_from_args(args: list[str]) -> bool:
    """Whether these interpreter arguments carry code or a file to load before the program: a flag from
    INLINE_CODE_FLAGS as a word, joined to its value, or in a short cluster; or an `eval` subcommand.
      ["-c", "import os"] -> True;  ["-cimport os"] -> True;  ["-Sc", "x"] -> True;  ["--eval=1"] -> True;
      ["-m", "my_server"] -> False;  ["server.py", "--config", "c.json"] -> False"""
    code_letters = {f[1] for f in INLINE_CODE_FLAGS if len(f) == 2}
    for a in args:
        if a in INLINE_CODE_FLAGS or a in INLINE_CODE_WORDS:
            return True
        if a.startswith("--") and a.split("=", 1)[0] in INLINE_CODE_FLAGS:
            return True
        if a.startswith("-") and not a.startswith("--") and len(a) > 2 and a[1] in code_letters:
            return True  # -cCODE, -MFoo, -e'...'
        if _SHORT_CLUSTER.match(a) and set(a[1:]) & code_letters:
            return True  # -Sc, -pe
    return False


def command_problem(spec: dict) -> str | None:
    """Why a stdio server's spec may not be run from the API, or None when it may. An MCP server is a program, so saving
    one is running code; what the API refuses is a spec that is nothing but a way to run arbitrary text: a shell as the
    command, an interpreter given code on its command line, or an env that hooks code into the program. Wrappers
    (env, nohup, xargs…) are looked through to the program they run; names are read without a path, spaces or a
    version; flags count joined or clustered; env keys are read without spaces or case.
    Examples: {"command": "/bin/sh", "args": ["-c", "id"]} -> "a shell isn't an MCP server";
    {"command": "env", "args": ["sh", "-c", "id"]} -> the same;
    {"command": "python3", "args": ["-c", "..."]} -> "code on the command line isn't an MCP server";
    {"command": "python3.12", "args": ["-cimport os"]} -> the same;
    {"command": "node", "env": {"NODE_OPTIONS": "--require x"}} -> "NODE_OPTIONS can't be set for a server";
    {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]} -> None;
    {"command": "python3", "args": ["-m", "my_server"]} -> None; {"url": ...} -> None (not a program)."""
    command = str(spec.get("command") or "")
    if not command:
        return None
    args = [str(a) for a in (spec.get("args") or [])]
    program = program_name(command)
    while program in WRAPPERS:  # env FOO=1 sh -c …: the program is the first word that is not an option or an assignment
        first = next((i for i, a in enumerate(args) if not a.startswith("-") and not (program == "env" and "=" in a)), None)
        if first is None:
            break
        program, args = program_name(args[first]), args[first + 1:]  # what follows keeps its own flags (-c …)
    if program in SHELLS:
        return "a shell isn't an MCP server"
    if program in INTERPRETERS and runs_code_from_args(args):
        return "code on the command line isn't an MCP server"
    env = spec.get("env") or {}
    hooked = next((k for k in env if str(k).strip().upper() in HOOK_VARS), None)
    if hooked is not None:
        return f"{str(hooked).strip().upper()} can't be set for a server"
    return None


def _session_id_of(readonly_context) -> str | None:
    """The chat a tool listing is for, from ADK's readonly context: a context with a session -> its id; None (a probe,
    a test) or a context without one -> None."""
    if readonly_context is None:
        return None
    session = getattr(readonly_context, "session", None)
    if session is None:
        return None
    return getattr(session, "id", None)


class PluginMcpToolset(McpToolset):
    """An MCP toolset whose tools need the user's tap, unless the user switched "Reading doesn't need a tap" on for
    the server (reads_free) and the tool's name says it reads (asks); the server's own read-only hint frees nothing.
    `smart` says whether the approvals mode is Smart right now (None: always Careful), and `allowed` whether a chat may
    use this server at all. Both are read on every listing, and the listing is made again at every step of a turn
    (ADK's per-invocation cache is off here: google/adk/tools/base_toolset.py get_tools_with_prefix), so a mode or a
    switch changed mid-chat shows on the next step. The server's own tool list is reused for LIST_CACHE_SECONDS, so a
    step costs no round trip to the server.

    Every tool it hands out carries the name of its server (`_odie_server`): two connections of one service list the
    same tool names, and which account a call reaches is a fact of the tool object ADK runs, not of its name
    (odie.plugins.access.server_of_call)."""

    def __init__(self, *args, reads_free: bool = False, smart: Callable[[str | None], bool] | None = None,
                 allowed: Callable[[str | None], bool] | None = None, server: str | None = None, **kwargs):
        # smart: reads the live mode for a chat (the session id, or None outside one) on every listing; see runs_free.
        # allowed: whether the chat (the session id, or None outside one) may use this server at all
        # (odie.plugins.access); None: every chat may. server: its name in mcp.json, stamped on its tools.
        super().__init__(*args, **kwargs)
        self._use_invocation_cache = False  # a listing per step: the switches and the mode are read live
        self.reads_free = reads_free
        self.smart = smart
        self.allowed = allowed
        self.server = server

    def _allowed_in(self, session_id: str | None) -> bool:
        """Whether this chat may use the server, read live on every listing (a switch flipped in Settings counts from
        the next step). A reader that fails counts as no: an app's tools are never listed in a thread where they might
        be off.
          no reader                         -> True
          Mira's thread, the server off for her -> False
          the reader raises                 -> False (logged)"""
        if self.allowed is None:
            return True
        try:
            return bool(self.allowed(session_id))
        except Exception:
            log.warning("could not read who may use an app; its tools are left out", exc_info=True)
            return False

    def _smart_now(self, session_id: str | None) -> bool:
        """Whether the approvals mode is Smart right now; Careful when there is no reader or it fails (a locked database
        must not drop the app's tools): reader says True -> True; reader raises -> False (logged)."""
        if not self.smart:
            return False
        try:
            return bool(self.smart(session_id))
        except Exception:
            log.warning("could not read the approvals mode; app tools ask as in Careful", exc_info=True)
            return False

    async def get_tools(self, readonly_context=None):
        session_id = _session_id_of(readonly_context)
        if not self._allowed_in(session_id):
            return []  # switched off for whoever this thread belongs to: none of its tools exist there
        tools = await super().get_tools(readonly_context)
        smart_now = self._smart_now(session_id)
        for t in tools:  # per tool; ADK's toolset option can't see annotations
            tool = {"name": t.name, "read_only": is_read_only(t), "destructive": is_destructive(t)}
            t._require_confirmation = asks(tool, self.reads_free, smart=smart_now)
            t._odie_server = self.server  # which connection this object reaches, whatever its name
            # Background turns share these tool objects and must never get Smart's looser rule: they read this instead.
            t._asks_in_careful = asks(tool, self.reads_free, smart=False)
        return tools


LIST_CACHE_SECONDS = 60  # how long a server's own tool list is reused between listings (PluginMcpToolset)


def toolset_for(name: str, spec: dict, timeout: float = 30, smart: Callable[[str | None], bool] | None = None,
                allowed: Callable[[str | None], bool] | None = None) -> PluginMcpToolset:
    if spec.get("url"):
        params = StreamableHTTPConnectionParams(url=spec["url"], headers=dict(spec.get("headers") or {}), timeout=timeout)
    else:
        env = {**server_env(), **(spec.get("env") or {})}
        params = StdioConnectionParams(server_params=StdioServerParameters(command=spec["command"], args=list(spec.get("args") or []), env=env),
                                       timeout=timeout)
    return PluginMcpToolset(connection_params=params, reads_free=bool(spec.get("readsFree")), smart=smart, allowed=allowed,
                            server=name, tool_list_cache_ttl_seconds=LIST_CACHE_SECONDS)


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MASK = "••••"
TOOL_APP: dict[str, str] = {}  # tool name -> the app (server title) it comes from, for approval cards
TOOL_SKILL: dict[str, str] = {}  # tool name -> the skill that loads it (mcp-<server>), to point a model that skipped it
# Tool name -> every working server that lists it (its name in mcp.json), in load order. Two connections of one service
# list the same names; they both load when no one has both switched on (load_servers), and which one a call reaches is
# the one on for the thread's owner (odie.plugins.access.server_of_tool).
TOOL_SERVERS: dict[str, list[str]] = {}
SERVER_TITLE: dict[str, str] = {}  # server -> the app's title, for approval cards and hints
SERVER_SKILL: dict[str, str] = {}  # server -> the skill that loads its tools (mcp-<server>); none for an always-on one


def skill_name_of(server: str) -> str:
    """The on-demand skill that brings a server's tools: "work-mail" -> "mcp-work-mail"."""
    return f"mcp-{server}"


def server_of_skill(skill: str) -> str | None:
    """The server whose skill this is, or None for any other skill: "mcp-work-mail" -> "work-mail"; "trackers" -> None."""
    if not skill.startswith("mcp-"):
        return None
    return skill.removeprefix("mcp-")


def _set_tool_servers(entries: list) -> None:
    """Which servers each tool name comes from, and each working server's title and skill, after a load; nothing stale
    stays."""
    by_tool: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    skills: dict[str, str] = {}
    for e in entries:
        if e.status != "ok":
            continue
        titles[e.name] = e.title or e.name
        if e.skill is not None:
            skills[e.name] = e.skill.name
        for tool in e.tools:
            by_tool.setdefault(tool, []).append(e.name)
    for registry, fresh in ((TOOL_SERVERS, by_tool), (SERVER_TITLE, titles), (SERVER_SKILL, skills)):
        registry.clear()
        registry.update(fresh)


def servers_with_tool(tool_name: str) -> list[str]:
    """Every working server that lists this tool, in load order: send_email from home and work mail -> ["mail",
    "mail-2"]; a tool no server lists -> []."""
    return list(TOOL_SERVERS.get(tool_name, []))


def _set_tool_apps(entries: list[tuple]) -> None:
    """(title, status, tools[, skill]) per server, after a load: only working apps name their tools; nothing stale
    stays."""
    names: dict[str, str] = {}
    skills: dict[str, str] = {}
    for title, status, tools, *skill in entries:
        if status == "ok":
            for t in tools:
                names.setdefault(t, title)
                if skill and skill[0]:
                    skills.setdefault(t, skill[0])
    TOOL_APP.clear()
    TOOL_APP.update(names)
    TOOL_SKILL.clear()
    TOOL_SKILL.update(skills)
log = logging.getLogger("odie.mcp")


@dataclass
class ServerEntry:
    name: str
    kind: str
    description: str
    status: str
    tools: list[str] = field(default_factory=list)
    always_on: bool = False
    enabled: bool = True
    reason: str = ""
    toolset: PluginMcpToolset | None = None
    skill: Skill | None = None
    title: str = ""


def mcp_path() -> Path:
    return config.settings.config_dir / "mcp.json"


def read_config() -> tuple[dict, str]:
    p = mcp_path()
    if not p.exists():
        return {}, ""
    if p.stat().st_mode & 0o077:  # written before it was kept owner-only, or by hand
        p.chmod(0o600)
    try:
        d = json.loads(p.read_text())
        servers = d.get("mcpServers") if isinstance(d, dict) else None
        return (servers if isinstance(servers, dict) else {}), ("" if isinstance(servers, dict) else "no mcpServers object")
    except ValueError as e:
        return {}, f"mcp.json is not valid JSON: {e}"


def write_config(servers: dict) -> None:
    """Owner-only (600): connected apps' keys and links sit in it."""
    p = mcp_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"mcpServers": servers}, indent=2))
    tmp.chmod(0o600)  # a temp file left from before keeps its old mode through O_TRUNC
    os.replace(tmp, p)


def server_env() -> dict:
    """What a command-line server needs to start the way it would in the user's terminal: launchd gives Odie a bare PATH,
    and npx/uv/brew tools live in Homebrew and ~/.local/bin."""
    home = os.environ.get("HOME", "")
    extra = ["/opt/homebrew/bin", "/usr/local/bin", f"{home}/.local/bin", f"{home}/.cargo/bin"]
    path = os.environ.get("PATH", "/usr/bin:/bin")
    path = ":".join([*(d for d in extra if d not in path.split(":")), path])
    env = {"PATH": path, "HOME": home, "SHELL": os.environ.get("SHELL", "/bin/zsh"), "LANG": os.environ.get("LANG", "en_US.UTF-8")}
    for k in ("USER", "LOGNAME", "TMPDIR"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


_SECRET_NAME = SECRET_NAME
_SECRET_VALUE = KEY_PREFIX
_LINK = re.compile(r"https?://[^\s'\"<>()]+")


def _mask_url(url: str) -> str:
    """Path segments and query values that look like keys, and query values named like secrets, become ••••."""
    from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit
    u = urlsplit(url)
    path = "/".join(MASK if secret_part(p) else p for p in u.path.split("/"))
    if path == u.path and not u.query:
        return url
    q = "&".join(f"{quote(k)}={MASK if _SECRET_NAME.search(k) or secret_part(v) else quote(v)}"
                 for k, v in parse_qsl(u.query, keep_blank_values=True)) if u.query else u.query
    return urlunsplit(u._replace(path=path, query=q))


def mask_links(text: str) -> str:
    """Every link in the text with its secret parts masked."""
    return _LINK.sub(lambda m: _mask_url(m.group(0)), text)


class MaskUrls(logging.Filter):
    """Log lines with the secret parts of their links masked: httpx logs every request's URL, and Zapier's key is in
    the path."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 (a record that can't format is left to logging)
            return True
        clean = mask_links(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and not record.exc_text:  # a traceback's last line repeats the error, link and all
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = mask_links(record.exc_text)  # formatters use exc_text when it is set
        return True


def install_log_masking() -> None:
    """MaskUrls on httpx's logger and on every handler of the root logger, once."""
    for target in (logging.getLogger("httpx"), *logging.getLogger().handlers):
        if not any(isinstance(f, MaskUrls) for f in target.filters):
            target.addFilter(MaskUrls())


def scrub(text: str, spec: dict) -> str:
    """Text shown or logged about a server (an error, a reason) with every secret of its spec, and the secret parts of
    any link, replaced by ••••."""
    from urllib.parse import parse_qsl, urlsplit
    found = [str(v) for k in ("env", "headers") for v in (spec.get(k) or {}).values()]
    found += [v.split(None, 1)[1] for v in list(found) if v.lower().startswith("bearer ") and " " in v.strip()]
    by_flag, bare = _arg_secrets(spec.get("args") or [])
    found += [*by_flag.values(), *bare]
    if isinstance(spec.get("url"), str):
        u = urlsplit(spec["url"])
        found += [p for p in u.path.split("/") if secret_part(p)]
        found += [v for k, v in parse_qsl(u.query) if _SECRET_NAME.search(k) or secret_part(v)]
    for secret in sorted({f for f in found if len(f) >= 6}, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return mask_links(text)


def _mask_args(args: list) -> list:
    out, hide_next = [], False
    for a in args:
        a = str(a)
        if hide_next:
            out.append(MASK)
            hide_next = False
        elif a.startswith("-") and "=" in a and _SECRET_NAME.search(a.split("=", 1)[0]):
            out.append(a.split("=", 1)[0] + "=" + MASK)
        elif a.startswith("-") and _SECRET_NAME.search(a):
            out.append(a)
            hide_next = True
        else:
            out.append(MASK if _SECRET_VALUE.match(a) else a)
    return out


def masked(spec: dict) -> dict:
    """The spec as Settings may show it: secret values in env, headers, URL query and arguments replaced by ••••."""
    out = dict(spec)
    for k in ("env", "headers"):
        if isinstance(out.get(k), dict):
            out[k] = {key: MASK for key in out[k]}
    if isinstance(out.get("url"), str):
        out["url"] = _mask_url(out["url"])
    if isinstance(out.get("args"), list):
        out["args"] = _mask_args(out["args"])
    return out


def _arg_secrets(args: list) -> tuple[dict[str, str], list[str]]:
    """Saved secrets in arguments: by flag ('--token v', '--token=v') and bare key-looking values in order."""
    by_flag: dict[str, str] = {}
    bare: list[str] = []
    args = [str(a) for a in args]
    for i, a in enumerate(args):
        if a.startswith("-") and "=" in a and _SECRET_NAME.search(a.split("=", 1)[0]):
            by_flag[a.split("=", 1)[0]] = a.split("=", 1)[1]
        elif a.startswith("-") and _SECRET_NAME.search(a) and i + 1 < len(args):
            by_flag[a] = args[i + 1]
        elif _SECRET_VALUE.match(a) and not (i > 0 and args[i - 1].startswith("-") and _SECRET_NAME.search(args[i - 1])):
            bare.append(a)
    return by_flag, bare


def unmask(new: dict, old: dict) -> dict:
    """A spec coming back from Settings: every masked value gets the saved secret it stood for. A mask with no saved
    counterpart (a renamed key, a new flag) raises ValueError, so a literal •••• is never saved as a secret."""
    out = dict(new)
    for k in ("env", "headers"):
        if isinstance(out.get(k), dict):
            restored = {}
            for key, v in out[k].items():
                if v == MASK:
                    if key not in (old.get(k) or {}):
                        raise ValueError(f"Re-enter the value for {key}: it's new, so there is no saved value to keep.")
                    v = old[k][key]
                restored[key] = v
            out[k] = restored
    from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit
    if isinstance(out.get("url"), str) and isinstance(old.get("url"), str) and urlsplit(out["url"]).netloc != urlsplit(old["url"]).netloc:
        if MASK in out["url"] or any(v == MASK for v in (new.get("headers") or {}).values()):
            raise ValueError("Re-enter the link's hidden parts and keys: its address changed, so the saved ones aren't sent there.")
    if isinstance(out.get("url"), str) and MASK in out["url"]:
        saved = dict(parse_qsl(urlsplit(old.get("url") or "").query, keep_blank_values=True))
        u = urlsplit(out["url"])
        if MASK in u.path:
            mine, theirs = u.path.split("/"), urlsplit(old.get("url") or "").path.split("/")
            if not old.get("url") or len(mine) != len(theirs):
                raise ValueError("Re-enter the link: it changed, so its hidden part can't be kept.")
            u = u._replace(path="/".join(theirs[i] if seg == MASK else seg for i, seg in enumerate(mine)))
        parts = []
        for k_, v in parse_qsl(u.query, keep_blank_values=True):
            if v == MASK:
                if k_ not in saved:
                    raise ValueError(f"Re-enter {k_} in the URL: there is no saved value to keep.")
                v = saved[k_]
            parts.append(f"{quote(k_)}={quote(v)}")
        out["url"] = urlunsplit(u._replace(query="&".join(parts) if u.query else u.query))
    if isinstance(out.get("args"), list) and any(MASK in str(a) for a in out["args"]):
        by_flag, bare = _arg_secrets(old.get("args") or [])
        args, res = [str(a) for a in out["args"]], []
        for i, a in enumerate(args):
            if a == MASK and i > 0 and args[i - 1] in by_flag:
                res.append(by_flag[args[i - 1]])
            elif a.endswith("=" + MASK) and a[: -len(MASK) - 1] in by_flag:
                res.append(a[: -len(MASK)] + by_flag[a[: -len(MASK) - 1]])
            elif a == MASK and bare:
                res.append(bare.pop(0))
            elif MASK in a:
                raise ValueError("An argument still shows •••• but has no saved value: re-enter it.")
            else:
                res.append(a)
        out["args"] = res
    return out


# How a mail app's results should look in chat. It goes into that app's skill, so the model reads it only after loading
# the skill, and the system prompt (and its block catalogue) stays the same size. The example is made up.
SHOW_MAIL = (
    "\n\nHow to show mail: list blocks and a sentence or two. Lists \"Needs you\" (sign, reply, pay, deadlines) then "
    "\"Also in\" (receipts, notifications); promos as one row (\"2 promos\"). Row: title \"Sender · subject\", subtitle "
    "the gist, value the time (\"11:30am\", \"Sat\"), icon alert (act), rupee (money), cal, ticket (events, travel), star "
    "(important), else mail; badges only where they matter. E.g. {\"title\":\"Asha · Lease renewal\",\"subtitle\":"
    "\":badge[Action] Sign by Friday\",\"value\":\"11:30am\",\"icon\":\"alert\",\"run\":\"Open the email from Asha "
    "about the lease renewal (id 18f3a2)\"}: run gives the mail's id"
)


def reads_mail(tools: list[str]) -> bool:
    """Does this app read mail? Yes when one of its tools is a mail listing, by the same names the watch looks for
    (odie.watch.sources.MAIL_RE). Example: ["gmail_search", "gmail_read", "calendar_list_events"] -> True (its skill
    says how to show mail); ["search_notes", "read_note"] -> False (a vault's skill stays as it was)."""
    from odie.watch.sources import MAIL_RE  # here, not at the top: odie.watch imports this module
    return any(MAIL_RE.match(t) for t in tools)


def _skill_for(name: str, description: str, tools: list[str]) -> Skill:
    fm = Frontmatter(name=skill_name_of(name), description=description, metadata={"adk_additional_tools": tools})
    instructions = f"Tools from the {name} MCP server: {', '.join(tools)}. Use them for: {description}"
    if reads_mail(tools):
        instructions += SHOW_MAIL
    return Skill(frontmatter=fm, instructions=instructions)


PROBE_ROOT = Path(__file__).resolve().parents[2]


def _descendants(pid: int) -> list[int]:
    """Every process below pid (the MCP library starts servers in their own process group, so killpg alone
    would miss them)."""
    try:
        rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=5).stdout.split("\n")
    except Exception:  # noqa: BLE001
        return []
    kids: dict[int, list[int]] = {}
    for row in rows:
        parts = row.split()
        if len(parts) == 2:
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    out, todo = [], [pid]
    while todo:
        for c in kids.get(todo.pop(), []):
            out.append(c)
            todo.append(c)
    return out


def _kill_tree(pid: int) -> None:
    """Freeze the helper first, so it can't start the server between the snapshot and the kill, then kill
    it and everything below it."""
    try:
        os.kill(pid, signal.SIGSTOP)
    except ProcessLookupError:
        return
    for p in [*_descendants(pid), pid]:
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def probe_tools(spec: dict, timeout: float) -> list[dict]:
    """The server's tools, listed by odie.plugins.probe in a separate process. On timeout the helper and every
    process under it (the server) are killed. Its stderr goes to a temp file, not a pipe, so an orphan holding
    it can't block. Raises TimeoutError or RuntimeError with the server's last words."""
    env = {**os.environ, "PYTHONPATH": str(PROBE_ROOT)}
    with tempfile.TemporaryFile() as errf:
        proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "odie.plugins.probe", stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=errf, env=env, start_new_session=True)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(json.dumps(spec).encode()), timeout)
        except BaseException as ex:  # timeout, or this listing was cancelled (reload, shutdown): leave nothing behind
            _kill_tree(proc.pid)
            if isinstance(ex, TimeoutError):
                await proc.wait()
                raise TimeoutError(f"timed out after {timeout:g} s") from None
            raise
        if proc.returncode != 0:
            errf.seek(0)
            last = (errf.read().decode(errors="replace").strip().splitlines() or ["no output"])[-1]
            raise RuntimeError(last[:200])
    return json.loads(out.decode().strip().splitlines()[-1])


async def load_servers(timeout: float = 15, reserved: dict[str, str] | None = None,
                       smart: Callable[[str | None], bool] | None = None,
                       allowed: Callable[[str, str | None], bool] | None = None,
                       may_share: Callable[[str, str], bool] | None = None) -> list[ServerEntry]:
    """Every server in mcp.json with its status. `reserved` maps tool names Odie already has (built-ins, skill
    tools) to their owner, so a server can't shadow them. `smart` reads the live approvals mode for each server's
    toolset. `allowed(server, session_id)` says whether a chat may use a server (odie.plugins.access), read on every
    listing. `may_share(a, b)` says whether two servers may list the same tool names (no one has both switched on);
    None: never, as before personalities."""
    servers, err = read_config()
    if err:
        log.warning(err)
    out: list[ServerEntry] = []
    seen: dict[str, str] = dict(reserved or {})  # tool name -> the built-in or skill that owns it
    by_servers: dict[str, list[str]] = {}  # tool name -> the servers loaded so far that list it
    for name, spec in servers.items():
        spec = spec if isinstance(spec, dict) else {}
        e = ServerEntry(name, "http" if spec.get("url") else "stdio", spec.get("description") or "", "ok",
                        always_on=bool(spec.get("alwaysOn")), enabled=spec.get("enabled", True) is not False)
        out.append(e)
        if not NAME_RE.match(name):
            e.status, e.reason = "error", "server names must be lower-case letters, digits and dashes"
            continue
        if not (spec.get("url") or spec.get("command")):
            e.status, e.reason = "error", "needs a command or a url"
            continue
        if not e.enabled:
            e.status = "disabled"
            continue
        try:
            listed = await probe_tools(spec, timeout)
        except Exception as ex:  # noqa: BLE001 (timeouts, refused connections, bad commands)
            e.status, e.reason = "failed", scrub(str(ex) or type(ex).__name__, spec)
            continue
        e.tools = [t["name"] for t in listed]
        e.title = spec.get("title") or name
        clash = _clash(e.tools, name, seen, by_servers, may_share)
        if clash:
            e.status, e.reason = "error", f"tool names clash with {clash}"
            continue
        for t in e.tools:
            by_servers.setdefault(t, []).append(name)
        e.toolset = toolset_for(name, spec, smart=smart, allowed=_allowed_for(name, allowed))  # connects lazily
        if not e.description:
            e.description = f"Tools from {name}: {', '.join(e.tools[:8])}"
        if not e.always_on:
            e.skill = _skill_for(name, e.description, e.tools)
    _set_tool_apps([(e.title or e.name, e.status, e.tools, e.skill.name if e.skill else None) for e in out])
    _set_tool_servers(out)
    return out


def _clash(tools: list[str], server: str, reserved: dict[str, str], by_servers: dict[str, list[str]],
           may_share: Callable[[str, str], bool] | None) -> str | None:
    """The first of a server's tools that it may not have, as "<tool> (<who has it>)", or None when it may load. A
    built-in's or a skill's tool name is never shared; another server's is, when may_share says no one has both on.
      write_note, already a built-in tool                         -> "write_note (Odie)"
      send_email, also in `mail`, both on for everyday Odie        -> "send_email (mail). Only one of them can be on…"
      send_email, also in `mail` (Odie's), this one Mira's alone   -> None: both load
      nothing in common                                            -> None"""
    for tool in tools:
        if tool in reserved:
            return f"{tool} ({reserved[tool]})"
        for other in by_servers.get(tool, []):
            shared_by_no_one = may_share is not None and may_share(other, server)
            if not shared_by_no_one:
                return f"{tool} ({other}). {ONE_OF_TWO}"
    return None


ONE_OF_TWO = "Only one of them can be on for each one: switch one of the two off, or off for whoever has both."


def _allowed_for(server: str, allowed: Callable[[str, str | None], bool] | None) -> Callable[[str | None], bool] | None:
    """load_servers' `allowed`, for one server: what its toolset asks with a chat's session id."""
    if allowed is None:
        return None

    def for_this_server(session_id: str | None) -> bool:
        return allowed(server, session_id)
    return for_this_server
