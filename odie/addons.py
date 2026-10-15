"""Add-ons: optional packages that plug features into Odie without changing its code (mail, a calendar, a money
ledger...). An add-on is a folder on the add-ons path (~/.odie/addons/, or the folders in ODIE_ADDONS separated by
":") holding a Python package whose __init__.py defines `register(odie) -> Addon`. `odie` is this module, so the
add-on builds its Addon from the types here. Every hook is optional; the core calls them where the feature fits
(the agent's tools, approval cards, prompt rules, routes, jobs, the brief, Up next) and carries on without any
hook that fails."""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("odie.addons")

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


@dataclass(frozen=True)
class Job:
    id: str                                      # scheduler job id, unique across Odie
    run: Callable[[Any, Any], Awaitable[None]]   # run(store, runner); runner is None in a server without one
    cron: dict[str, Any]                         # CronTrigger fields, e.g. {"minute": "15,45", "hour": "7-22"}
    about: str                                   # what About says runs on its own
    misfire: int = 600


@dataclass(frozen=True)
class Card:
    summary: str
    detail: dict[str, Any]
    risk: str = "normal"                         # "unknown" when code can't confirm what will happen


@dataclass(frozen=True)
class Nudge:
    tool: str                                    # the call the model should have made
    text: str                                    # said once to the model, out of the user's sight
    note: str                                    # shown to the user if the retry still doesn't make it


@dataclass(frozen=True)
class BriefPart:
    key: str                                     # stored with the brief, e.g. "calendar"
    title: str                                   # the heading the brief's model reads
    text: str | None                             # None: not connected (said as such); "": nothing today


class TurnCheck(Protocol):
    def see(self, event: Any) -> None: ...
    def missing(self, user_text: str, called: set[str]) -> Nudge | None: ...


def _no_caps() -> frozenset[str]:
    return frozenset()


def _no_tools(store: Any) -> list:
    return []


@dataclass
class Addon:
    name: str
    capabilities: Callable[[], frozenset[str]] = _no_caps
    tools: Callable[[Any], list] = _no_tools                 # tools and toolsets for the agent
    tool_names: frozenset[str] = frozenset()                 # names its tools use; no skill or app may reuse one
    gated: frozenset[str] = frozenset()                      # need the user's tap: no step chip, refused in background
    untrusted: frozenset[str] = frozenset()                  # results are other people's text: fenced for the model
    clamp: dict[str, int] = field(default_factory=dict)      # tool -> characters of its result the model sees
    rules: list = field(default_factory=list)                # odie.agent.prompt.Rule
    card: Callable[[str, dict, str, Any], Card | None] | None = None              # (tool, args, session_id, store)
    after_tool: Callable[[str, dict, Any, Any, str | None, str | None], None] | None = None
    # ^ (tool, args, result, store, session_id, invocation_id)
    turn_check: Callable[[], TurnCheck] | None = None
    after_turn: Callable[[Any, str, str], Awaitable[None]] | None = None          # (runner, turn_started, session_id)
    router: Any = None                                       # a FastAPI APIRouter, mounted under /api
    jobs: list[Job] = field(default_factory=list)
    abilities: list[tuple[str, tuple[str, ...], str]] = field(default_factory=list)   # About: (label, tools, text)
    connections: Callable[[], Awaitable[dict[str, bool]]] | None = None             # merged into /api/health
    brief: Callable[[Any, datetime, Any], Awaitable[list[BriefPart]]] | None = None  # (store, now, post_message)
    brief_guidance: list[str] = field(default_factory=list)  # lines for the brief's instructions
    upcoming: Callable[[Any, datetime, int], Awaitable[tuple[list[dict], dict[str, bool]]]] | None = None
    watch_sources: Callable[[Any], list] | None = None      # (store) -> [odie.watch.sources.Source]: mail and calendar it reads
    thread_hints: dict[str, Callable[[Any], str]] = field(default_factory=dict)    # source_kind -> " · source: ..."
    start: Callable[[], None] | None = None                  # once, when the server starts
    task_done: Callable[[str, str], Awaitable[str | None]] | None = None  # (source_kind, ref) -> a note; None: not its kind
    prefetch: Callable[[str, list[str]], Awaitable[str]] | None = None    # (question, previous ones) -> a ready block, or ""
    blocks: tuple[tuple[str, str], ...] = ()                 # how its prefetched blocks open and close (old turns lose them)


@dataclass
class Found:
    name: str
    path: Path
    status: str                                  # "ok" | "failed"
    reason: str = ""
    addon: Addon | None = None


def _one_line(e: BaseException) -> str:
    return (f"{type(e).__name__}: {e}".splitlines() or [type(e).__name__])[0][:300]


def load_one(path: Path) -> Found:
    """Import one add-on folder as the package odie_addon_<name> and register it."""
    name = path.name
    if not NAME_RE.match(name):
        return Found(name, path, "failed", "add-on folder names are lower-case letters, digits and _")
    module = f"odie_addon_{name}"
    for m in [m for m in sys.modules if m == module or m.startswith(module + ".")]:
        del sys.modules[m]  # a fresh import each time: the same name may come from another folder
    try:
        spec = importlib.util.spec_from_file_location(module, path / "__init__.py", submodule_search_locations=[str(path)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module] = mod
        spec.loader.exec_module(mod)
        register = getattr(mod, "register", None)
        if not callable(register):
            raise TypeError("the add-on has no register(odie) function")
        addon = register(sys.modules[__name__])
        if not isinstance(addon, Addon):
            raise TypeError(f"register() returned {type(addon).__name__}, not an Addon")
        if addon.name != name:
            raise ValueError(f"register() named the add-on {addon.name!r}, but its folder is {name}")
        _check(addon)
    except Exception as e:  # noqa: BLE001
        sys.modules.pop(module, None)
        log.warning("add-on %s failed to load", name, exc_info=True)
        return Found(name, path, "failed", _one_line(e))
    return Found(name, path, "ok", "", addon)


def _check(addon: Addon) -> None:
    """The declarations Odie acts on at startup (jobs, routes, rules) are checked here, so a bad one fails this add-on
    instead of stopping Odie."""
    from apscheduler.triggers.cron import CronTrigger

    from odie.agent.prompt import Rule
    for j in addon.jobs:
        if not isinstance(j, Job):
            raise TypeError(f"jobs must be odie.Job, not {type(j).__name__}")
        CronTrigger(**j.cron)  # raises on a field it doesn't know or a value it can't read
    if addon.router is not None and not isinstance(getattr(addon.router, "routes", None), list):
        raise TypeError("router must be a FastAPI APIRouter")
    for r in addon.rules:
        if not isinstance(r, Rule):
            raise TypeError(f"rules must be odie.agent.prompt.Rule, not {type(r).__name__}")


def load(dirs: Iterable[Path]) -> list[Found]:
    """Every add-on folder in each dir, by name. A second add-on with a name or a tool name already taken is refused."""
    out: list[Found] = []
    owner: dict[str, str] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        try:
            paths = sorted(p for p in d.iterdir() if (p / "__init__.py").is_file())
        except OSError:
            log.warning("add-ons folder %s can't be read; skipped", d, exc_info=True)
            continue
        for path in paths:
            if any(f.name == path.name and f.status == "ok" for f in out):
                out.append(Found(path.name, path, "failed", f"an add-on named {path.name} is already loaded"))
                continue
            f = load_one(path)
            if f.addon is not None:
                clash = sorted({owner[t] for t in f.addon.tool_names if t in owner})
                if clash:
                    f = Found(f.name, path, "failed", f"tool names clash with {', '.join(clash)}")
                else:
                    owner.update({t: f.name for t in f.addon.tool_names})
            out.append(f)
    return out


_found: list[Found] | None = None


def found() -> list[Found]:
    """The add-ons on the settings' path, loaded once."""
    global _found
    if _found is None:
        from odie import config
        _found = load(config.settings.addons_dirs)
    return _found


def active() -> list[Addon]:
    return [f.addon for f in found() if f.status == "ok" and f.addon is not None]


def refuse(name: str, reason: str) -> None:
    """Take a loaded add-on out (it clashes with the core, say): it shows as failed, with the reason."""
    for f in found():
        if f.name == name and f.status == "ok":
            f.status, f.reason = "failed", reason
            log.warning("add-on %s refused: %s", name, reason)


def use(addons: list[Addon] | None) -> None:
    """Tests: make exactly these add-ons active. None loads from the add-ons path again on next use."""
    global _found
    _found = None if addons is None else [Found(a.name, Path(a.name), "ok", "", a) for a in addons]


def call(hook: str, *args) -> list:
    """Every active add-on's hook result, in order. A raising hook is logged and left out."""
    out = []
    for a in active():
        fn = getattr(a, hook, None)
        if fn is None:
            continue
        try:
            out.append(fn(*args))
        except Exception:  # noqa: BLE001
            log.warning("add-on %s: %s failed", a.name, hook, exc_info=True)
    return out


async def acall(hook: str, *args) -> list:
    """The same for async hooks."""
    out = []
    for a in active():
        fn = getattr(a, hook, None)
        if fn is None:
            continue
        try:
            out.append(await fn(*args))
        except Exception:  # noqa: BLE001
            log.warning("add-on %s: %s failed", a.name, hook, exc_info=True)
    return out


def capabilities() -> frozenset[str]:
    return frozenset().union(*call("capabilities"))


def gated_tools() -> frozenset[str]:
    return frozenset().union(*(a.gated for a in active()))


def tool_names() -> frozenset[str]:
    return frozenset().union(*(a.tool_names for a in active()))


def untrusted_tools() -> frozenset[str]:
    return frozenset().union(*(a.untrusted for a in active()))


def clamps() -> dict[str, int]:
    return {k: v for a in active() for k, v in a.clamp.items()}


def tools_of(addon: Addon, store: Any) -> list:
    """An add-on's tools, each tagged with its name (so a reload can find them). A failing hook gives none."""
    try:
        tools = list(addon.tools(store))
    except Exception:  # noqa: BLE001
        log.warning("add-on %s: tools failed", addon.name, exc_info=True)
        return []
    for t in tools:
        t._odie_addon = addon.name
    return tools


def block_marks() -> list[tuple[str, str]]:
    return [m for a in active() for m in a.blocks]


async def source_done(kind: str, ref: str) -> str | None:
    """A thread was closed here: the first add-on that owns its kind closes it at the source too, and says so."""
    for note in await acall("task_done", kind, ref):
        if note:
            return str(note)
    return None


def rules() -> list:
    """Every active add-on's prompt rules, in add-on order."""
    return [r for a in active() for r in a.rules]
