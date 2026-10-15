"""Skills Odie can load: built-in ones (odie/skills/) and the user's own (~/.odie/skills/). A skill is a
folder with SKILL.md and, optionally, tools.py defining TOOLS. The user's skills with code stay blocked until they
allow them; the allowance is tied to a hash of the code, so a changed tools.py asks again."""
from __future__ import annotations

import hashlib
import logging
import types
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.skills import load_skill_from_dir
from google.adk.skills.models import Skill
from google.adk.tools import BaseTool, FunctionTool

from odie import config
from odie.store.db import Store

BUILTIN = Path(__file__).parent
log = logging.getLogger("odie.skills")


@dataclass
class SkillEntry:
    name: str
    description: str
    source: str
    status: str
    tools: list[str]
    reason: str = ""
    path: Path | None = None
    code_hash: str = ""
    skill: Skill | None = None
    tool_objs: list = field(default_factory=list)


def shown_as(e: SkillEntry) -> tuple[str, str]:
    """A skill's title and one line for Settings → Skills: its metadata's own `title` and `summary` when it has them
    (written for people), else the name tidied and the description up to where it starts telling the model when to
    use it.
      about-odie with title "About Odie"                         -> ("About Odie", its summary)
      weekly-review, "A Sunday review of my week. Use for …"  -> ("Weekly review", "A Sunday review of my week.")"""
    meta = {}
    if e.skill is not None:
        meta = e.skill.frontmatter.metadata or {}
    title = str(meta.get("title") or e.name.replace("-", " ").replace("_", " ").capitalize())
    summary = str(meta.get("summary") or "")
    if not summary:
        summary = e.description
        for marker in (" Use for ", " Use when ", " Use it "):
            if marker in summary:
                summary = summary.split(marker, 1)[0]
    return title, summary.strip()


def _code_hash(d: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(d.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        h.update(f.relative_to(d).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


_TOOLS_CACHE: dict[tuple[str, str], list] = {}  # (folder, code hash) -> tools: import each version of tools.py once


def _load_tools(d: Path, name: str, code_hash: str = "") -> list:
    key = (str(d), code_hash)
    if code_hash and key in _TOOLS_CACHE:
        return _TOOLS_CACHE[key]
    # Compiled from the source text (the code the trust hash covers), never from a __pycache__ file, and nothing is written.
    src = (d / "tools.py").read_bytes()
    mod = types.ModuleType(f"odie_skill_{name.replace('-', '_')}")
    mod.__file__ = str(d / "tools.py")
    exec(compile(src, str(d / "tools.py"), "exec"), mod.__dict__)  # noqa: S102 (a skill's own code, allowed by the user)
    raw = getattr(mod, "TOOLS", None)
    if not isinstance(raw, list) or not raw:
        raise ValueError("tools.py defines no TOOLS list")
    tools = [t if isinstance(t, BaseTool) else FunctionTool(t) for t in raw]
    if code_hash:
        _TOOLS_CACHE[key] = tools
    return tools


def _entry(d: Path, source: str, store: Store) -> SkillEntry:
    name = d.name
    try:
        skill = load_skill_from_dir(d)
        name = skill.frontmatter.name
        has_code = (d / "tools.py").exists()
        code_hash = _code_hash(d) if has_code else ""
        e = SkillEntry(name, skill.frontmatter.description, source, "ok", [], path=d, code_hash=code_hash, skill=skill)
        untrusted = has_code and source == "user" and (store.get_setting("skills.trusted") or {}).get(name) != code_hash
        if name in (store.get_setting("skills.disabled") or []):
            e.status = "disabled"
            if untrusted:
                e.reason = "its code changed: it will need your OK when you switch it on"
            return e  # switched off: its code doesn't run either
        if untrusted:
            e.status, e.reason = "blocked", "runs code on this computer: needs your OK"
            return e  # never import code that isn't allowed
        if has_code:
            e.tool_objs = _load_tools(d, name, code_hash)
            e.tools = [t.name for t in e.tool_objs]
            meta = skill.frontmatter.metadata
            meta.setdefault("adk_additional_tools", e.tools)
        return e
    except KeyboardInterrupt:
        raise
    except BaseException as ex:  # noqa: BLE001 (a tools.py calling sys.exit must not stop Odie)
        log.warning("skill %s failed to load", d, exc_info=True)
        return SkillEntry(name, "", source, "error", [], reason=f"{type(ex).__name__}: {str(ex)[:160]}", path=d)


def discover(store: Store, builtin_dir: Path = BUILTIN, user_dir: Path | None = None) -> list[SkillEntry]:
    user_dir = user_dir if user_dir is not None else config.settings.config_dir / "skills"
    found: dict[str, SkillEntry] = {}
    for source, root in (("builtin", builtin_dir), ("user", user_dir)):
        if not root.is_dir():
            continue
        for d in sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").exists()):
            e = _entry(d, source, store)
            found[e.name] = e  # a user skill with a built-in's name replaces it
    return sorted(found.values(), key=lambda e: e.name)


def trust(store: Store, entry: SkillEntry) -> None:
    trusted = dict(store.get_setting("skills.trusted") or {})
    trusted[entry.name] = entry.code_hash
    store.set_setting("skills.trusted", trusted)


def set_enabled(store: Store, name: str, enabled: bool) -> None:
    off = set(store.get_setting("skills.disabled") or [])
    (off.discard if enabled else off.add)(name)
    store.set_setting("skills.disabled", sorted(off))
