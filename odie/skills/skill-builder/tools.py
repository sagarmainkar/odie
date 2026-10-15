"""Tools the skill-builder skill brings: guide, read, draft (checked, nothing runs), install (needs the user's tap)."""
from google.adk.tools import FunctionTool

from odie.skills import builder


async def skill_guide() -> str:
    """How to write a Odie skill: the SKILL.md and tools.py rules, the visual blocks and icons the app can draw,
    and the tool names already taken. Call this first when building or changing a skill."""
    return builder.guide()


async def read_skill(name: str) -> str:
    """The SKILL.md and tools.py of an existing skill: one of the user's (to change it) or a built-in one such as
    stocks (as a worked example)."""
    for root in (builder.user_dir(), builder.BUILTIN_DIR):
        d = root / name
        if (d / "SKILL.md").exists():
            parts = [f"── {f} ──\n{(d / f).read_text()}" for f in ("SKILL.md", "tools.py") if (d / f).exists()]
            return "\n".join(parts)
    return f"No skill named '{name}'."


async def draft_skill(name: str, description: str, instructions: str, tools_code: str = "", blocks: list[str] | None = None) -> str:
    """Write a skill into staging and check it (its code is read, never run). name: lowercase-with-hyphens.
    description: one line, what it does and when to use it. instructions: the SKILL.md body in Markdown.
    tools_code: the whole tools.py, or "" for an instructions-only skill. blocks: the block kinds it draws.
    Returns "Ready to install" or the problems to fix; call again with fixes until it's ready."""
    return await builder.draft(name, description, instructions, tools_code, blocks)


async def install_skill(name: str, version: str) -> str:
    """Install a drafted skill that draft_skill said is ready, with the version it gave. The user sees an approval card
    with the skill's text and code; it installs (and its code is allowed) only when the user taps Approve."""
    return await builder.install(name, version)


TOOLS = [FunctionTool(skill_guide), FunctionTool(read_skill), FunctionTool(draft_skill),
         FunctionTool(install_skill, require_confirmation=True)]
