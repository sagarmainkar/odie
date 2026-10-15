"""What the model sees, rendered for a fixed day: the system prompt (as is, and with the assistant renamed the way
the runner does it), the per-turn context, the voice instructions, the brief's instructions and the local tools'
declarations. tests/test_golden.py compares these with tests/golden/. After an intended change, rewrite them with
`uv run python -m tests.golden_render --write` and review the diff."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

GOLDEN = Path(__file__).parent / "golden"
NOW = datetime(2026, 10, 1, 7, 45, tzinfo=ZoneInfo("Asia/Kolkata"))
MEMORY_INDEX = "## Identity\n- Name and family\n## Travel\n- Flight seat preference"


def _tool_declarations(tmp: Path) -> str:
    from google.adk.tools import FunctionTool

    from odie import addons
    from odie.agent.tools.local import make_local_tools
    from odie.agent.tools.files import make_file_tools
    from odie.agent.tools.media import make_media_tools
    from odie.agent.tools.shell import make_shell_tool
    from odie.agent.tools.web import make_web_tools
    from odie.memory.store import MemoryFile
    from odie.memory.tools import make_memory_tools
    from odie.store.db import Store
    store = Store(tmp / "golden.db")
    store.init_schema()
    memory = MemoryFile(tmp / "memories.md", tmp / "memory.lock", "golden")
    tools = [*make_memory_tools(memory), make_shell_tool(store=store), *make_web_tools(api_key=""),
             *make_local_tools(store, "Asia/Kolkata"), *make_media_tools(store), *make_file_tools()]
    tools += [t for a in addons.active() for t in addons.tools_of(a, store) if isinstance(t, FunctionTool)]  # MCP ones list online
    from odie.skills.registry import discover
    tools += [t for e in discover(store) if e.status == "ok" for t in e.tool_objs]  # declared from the start (odie.skills)
    decls = [t._get_declaration().model_dump(exclude_none=True, mode="json") for t in tools]
    return json.dumps(sorted(decls, key=lambda d: d["name"]), indent=2, ensure_ascii=False)


def render(tmp: Path) -> dict[str, str]:
    from odie import persona
    from odie.agent.prompt import Who, build_static_prompt, build_turn_context
    from odie.jobs.brief import brief_system, guidance
    from odie.voice import realtime_instructions
    soul = f"You are {persona.DEFAULT_NAME}, calm and dry-witted. Short answers."
    who = Who(user="Asha", machine="Mac", currency="₹")
    gated = build_static_prompt(NOW, None, MEMORY_INDEX, gated=True, who=who)
    out = {
        "static_gated.txt": gated,
        "static_minimal.txt": build_static_prompt(NOW, None, MEMORY_INDEX, gated=True,
                                                  who=Who(user="Asha", machine="computer", currency="$", caps=frozenset())),
        "static_gated_iris.txt": persona.apply_name(gated, "Iris"),  # what the runner sends when the assistant is "Iris"
        "static_draft_only.txt": build_static_prompt(NOW, None, MEMORY_INDEX, gated=False, who=who),
        "static_soul_renamed.txt": persona.apply_name(build_static_prompt(NOW, soul, MEMORY_INDEX, gated=True, who=who), "Iris"),
        "turn_context.txt": build_turn_context(NOW, "### Flight Seat Preference\nAisle.", "Open threads: 2 to do.",
                                               "#1 [reminder] Card bill · due 2026-10-03", "Two things today."),
        "voice_instructions.txt": realtime_instructions("Iris", None, "Open threads: 2 to do.", user="Asha"),
        "brief_system.txt": brief_system("Asha", guidance()),
        "tool_declarations.json": _tool_declarations(tmp),
    }
    return {name: text if text.endswith("\n") else text + "\n" for name, text in out.items()}


if __name__ == "__main__":
    root = Path(tempfile.mkdtemp(prefix="odie-golden-"))
    os.environ.pop("ODIE_HOME", None)
    for key, sub in (("DATA_DIR", "data"), ("CONFIG_DIR", "config"), ("MEMORY_FILE", "memories.md")):
        os.environ[f"ODIE_{key}"] = str(root / sub)  # never the real folders
    os.environ["ODIE_PREFETCH"] = "0"
    os.environ["ODIE_ADDONS"] = ""  # the core alone, unless --addon names one (never a real home's)
    target = GOLDEN
    if "--addon" in sys.argv:  # an add-on's own snapshot: --addon addons/mine writes addons/mine/tests/golden
        from odie import addons
        folder = Path(sys.argv[sys.argv.index("--addon") + 1]).resolve()
        found = addons.load_one(folder)
        assert found.status == "ok", found.reason
        addons.use([found.addon])
        target = folder / "tests" / "golden"
    files = render(root)
    if "--write" in sys.argv:
        target.mkdir(exist_ok=True)
        for name, text in files.items():
            (target / name).write_text(text)
        print(f"wrote {len(files)} files to {target}")
    else:
        print("\n".join(sorted(files)))
