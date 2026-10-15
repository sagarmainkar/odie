"""The skill builder's engine: Odie drafts a skill into a staging folder, checks it without running any of its code,
and installs it only after the user taps Approve (which also trusts that exact code). The code was written by a model
that may have read web pages, so nothing in it runs before the tap; the checks only read it."""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from google.adk.skills import load_skill_from_dir

from odie import config
from odie.blocks import CHART_KINDS, catalog_text, kinds, load_catalog

# Set by the runner: the store (for trust), a plugin reload, and the tool names already taken.
hooks: dict = {"store": None, "reload": None, "reserved": None}

NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
BUILTIN_DIR = Path(__file__).parent
_FENCE_KINDS = re.compile(r'"type"\s*:\s*"([a-z_-]+)"')
_ICONS = re.compile(r'"icon"\s*:\s*"([a-z_-]+)"')
_ALLOWED_TOP = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)


def staging_dir() -> Path:
    return config.settings.config_dir / "skills-staging"


def user_dir() -> Path:
    return config.settings.config_dir / "skills"


def builtin_names() -> set[str]:
    return {d.name for d in BUILTIN_DIR.iterdir() if (d / "SKILL.md").exists()}


def name_problem(name: str) -> str | None:
    if not NAME_RE.match(name or "") or len(name) > 40:
        return "Name it in lowercase words joined by hyphens, like travel-itinerary."
    if name in builtin_names() or name.startswith("mcp-"):
        return f"'{name}' is taken by a built-in skill or a connected app; pick another name."
    return None


def check_code(code: str, reserved: dict[str, str] | None = None) -> list[str]:
    """Problems in a tools.py, found by reading it (never running it)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"tools.py has a syntax error on line {e.lineno}: {e.msg}."]
    probs: list[str] = []
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    tools_node = None
    for i, n in enumerate(tree.body):
        if i == 0 and isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            continue  # module docstring
        if not isinstance(n, _ALLOWED_TOP):
            probs.append(f"Line {n.lineno} runs when the file is imported; keep top-level code to imports, functions and constants.")
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TOOLS" for t in n.targets):
            tools_node = n.value
    for n in ast.walk(tree):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level else []
        for m in mods:
            top = m.split(".")[0]
            if top not in sys.stdlib_module_names and importlib.util.find_spec(top) is None:
                probs.append(f"tools.py imports {m}, which isn't installed; use the standard library, httpx or google.adk.")
    if not isinstance(tools_node, ast.List) or not tools_node.elts:
        probs.append("tools.py must end with TOOLS = [FunctionTool(your_function), ...].")
        return probs
    for el in tools_node.elts:
        ref = el.args[0] if isinstance(el, ast.Call) and el.args else el
        fname = ref.id if isinstance(ref, ast.Name) else None
        f = funcs.get(fname or "")
        if not f:
            probs.append(f"TOOLS lists {ast.unparse(el)}, but tools.py defines no function {fname or ast.unparse(el)}.")
            continue
        if not ast.get_docstring(f):
            probs.append(f"{f.name} needs a docstring: it's what the model reads to know when and how to call it.")
        if reserved and f.name in reserved:
            probs.append(f"A tool named {f.name} already exists ({reserved[f.name]}); rename yours.")
    return probs


def check_text(text: str, blocks: list[str]) -> list[str]:
    """Block kinds and icon names used in the instructions or code must exist in the catalogue."""
    known, icons = kinds(), set(load_catalog()["icons"])
    probs = [f"There's no '{b}' block; the blocks are: {', '.join(sorted(known))}." for b in blocks if b not in known]
    for k in sorted(set(_FENCE_KINDS.findall(text)) - known - CHART_KINDS):
        probs.append(f"'{k}' isn't a block the app can draw; use one from the catalogue.")
    for i in sorted(set(_ICONS.findall(text)) - icons):
        probs.append(f"There's no '{i}' icon; the icons are listed in the guide.")
    return probs


def _skill_md(name: str, description: str, instructions: str, blocks: list[str]) -> str:
    desc = " ".join(description.split())
    meta = f"metadata:\n  blocks: [{', '.join(blocks)}]\n" if blocks else ""
    return f"---\nname: {name}\ndescription: {json.dumps(desc, ensure_ascii=False)}\n{meta}---\n{instructions.strip()}\n"


async def draft(name: str, description: str, instructions: str, tools_code: str = "", blocks: list[str] | None = None) -> str:
    blocks = list(blocks or [])
    if p := name_problem(name):
        return p
    if not description.strip() or not instructions.strip():
        return "Give the skill a one-line description (what Odie sees when choosing a skill) and its instructions."
    d = staging_dir() / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(_skill_md(name, description, instructions, blocks))
    probs: list[str] = []
    if tools_code.strip():
        (d / "tools.py").write_text(tools_code)
        reserved = hooks["reserved"]() if hooks.get("reserved") else {}
        probs += check_code(tools_code, reserved)
    probs += check_text(instructions + "\n" + tools_code, blocks)
    try:
        load_skill_from_dir(d)  # parses SKILL.md only; runs no code
    except Exception as e:  # noqa: BLE001
        probs.append(f"SKILL.md doesn't parse: {e}")
    if probs:
        return "Not ready. Fix these, then call draft_skill again:\n- " + "\n- ".join(probs)
    kind = "with code (tools.py)" if tools_code.strip() else "instructions only"
    replaces = ""
    if (user_dir() / name).is_dir():
        kept = _kept_files(name)
        replaces = f" This replaces your {name} skill's SKILL.md and tools.py" + (f"; keeps your other files: {', '.join(kept)}" if kept else "") + "."
    return (f"Ready to install: {name}, {kind}.{replaces} Call install_skill(name='{name}', version='{staged_version(name)}'). The user "
            "gets an approval card showing the skill; nothing is installed until they tap Approve.")


def _kept_files(name: str) -> list[str]:
    """Files of an existing user skill that an update leaves alone (helpers, references)."""
    dest = user_dir() / name
    if not dest.is_dir():
        return []
    return sorted(f"{p.name}/" if p.is_dir() else p.name for p in dest.iterdir()
                  if p.name not in ("SKILL.md", "tools.py", "__pycache__") and not p.name.startswith("."))


def staged_version(name: str) -> str:
    """A stamp of the staged files: what the user approved must be what gets installed."""
    import hashlib
    d = staging_dir() / name
    h = hashlib.sha256()
    for f in ("SKILL.md", "tools.py"):
        if (d / f).exists():
            h.update(f.encode() + b"\0" + (d / f).read_bytes() + b"\0")
    return h.hexdigest()[:12]


def staged_text(name: str) -> str:
    """What the approval card shows: SKILL.md and tools.py, as written."""
    d = staging_dir() / name
    parts = []
    if (user_dir() / name).is_dir():
        kept = _kept_files(name)
        parts.append(f"── Replaces your existing {name} skill" + (f"; keeps: {', '.join(kept)}" if kept else "") + " ──")
    for f in ("SKILL.md", "tools.py"):
        if (d / f).exists():
            parts.append(f"── {f} ──\n{(d / f).read_text()}")
    return "\n".join(parts)


async def install(name: str, version: str = "") -> str:
    """Runs only after the user approved: move the draft in, trust its code, reload, and report how it loaded."""
    from odie.skills.registry import _code_hash, discover, trust
    src = staging_dir() / name
    if name_problem(name) or not (src / "SKILL.md").exists():
        return f"No draft named '{name}'. Call draft_skill first."
    if version != staged_version(name):
        return ("The draft changed after this install was asked for, so it wasn't installed. Call install_skill again "
                "with the version draft_skill gave last; the user approves that one.")
    dest = user_dir() / name
    user_dir().mkdir(parents=True, exist_ok=True)
    if dest.is_dir():  # an update: replace what the card showed, keep the user's other files
        shutil.copy2(src / "SKILL.md", dest / "SKILL.md")
        if (src / "tools.py").exists():
            shutil.copy2(src / "tools.py", dest / "tools.py")
        else:
            (dest / "tools.py").unlink(missing_ok=True)  # code the card didn't show must not stay behind, trusted
        shutil.rmtree(dest / "__pycache__", ignore_errors=True)
        shutil.rmtree(src, ignore_errors=True)
    else:
        shutil.move(str(src), str(dest))
    store = hooks["store"]
    if (dest / "tools.py").exists():
        trusted = dict(store.get_setting("skills.trusted") or {})
        trusted[name] = _code_hash(dest)
        store.set_setting("skills.trusted", trusted)
    if hooks.get("reload"):
        await hooks["reload"]()
    entry = next((e for e in discover(store, user_dir=user_dir()) if e.name == name), None)
    if not entry or entry.status == "error":
        why = entry.reason if entry else "it wasn't found after installing"
        return (f"Installed {name}, but it didn't load: {why}. Fix it with draft_skill and install again "
                "(that asks the user once more).")
    store.audit("agent", "skill_installed", result_summary=name)
    tools = f" Its tools: {', '.join(entry.tools)}." if entry.tools else ""
    return (f"The user approved it and {name} is installed now; it's on and loads on demand.{tools} Tell them it's ready "
            "(no more taps needed), with one example request to try.")


def guide() -> str:
    reserved = sorted(hooks["reserved"]()) if hooks.get("reserved") else []
    return f"""How to write a Odie skill.

A skill is a folder: SKILL.md (instructions) and, only if needed, tools.py (code). Odie sees each skill's
one-line description and loads the instructions when a request matches, so the description says what the skill
does and when to use it.

Prefer instructions only: they can tell Odie how to use the tools it already has (below) and which blocks to
draw. Add tools.py only for what instructions can't do reliably: calling an API, calculating, or building block
JSON from data.

tools.py rules:
- Top level: imports, constants and functions only, ending with TOOLS = [FunctionTool(fn), ...]
  (from google.adk.tools import FunctionTool).
- Each tool is an async function with simple typed arguments (str, int, float, bool, list[str]) and a docstring
  saying what it returns and when to call it. Return a str. Never raise: return one plain sentence on failure.
- Libraries: the standard library, httpx (use a timeout) and google.adk. No API keys in the code.
- To show visuals, return text that includes a ```odie-blocks fence with a JSON list of blocks, and tell
  Odie in SKILL.md to paste that block unchanged.
- Tool names must be new. Taken: {", ".join(reserved)}.

Visual blocks the app can draw (use only these kinds and icon names):

{catalog_text()}
"""
