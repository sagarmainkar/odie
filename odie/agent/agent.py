"""The one agent. `root_agent` is resolved lazily so `adk web odie/agent` can load the same thing
without tests touching the real data directory."""
from __future__ import annotations

from collections.abc import Callable

from google.adk.agents import LlmAgent
from google.genai import types

from odie.agent.model import model_for
from odie.agent.prompt import IDENTITY, Who, rules_text
from odie.agent.tools.local import make_local_tools
from odie.agent.tools.shell import make_shell_tool
from odie.agent.tools.web import make_web_tools
from odie.memory.store import MemoryFile
from odie.memory.tools import make_memory_tools
from odie.models import resolve_selection
from odie.sampling import CHAT_TOP_P, chat_temperature
from odie.skills import build_skill_toolset
from odie import config
from odie.store.db import Store

GATED_TOOLS = frozenset({"run_shell", "install_skill"})
CORE_NAMES = frozenset({"load_skill", "unload_skill", "load_skill_resource", "list_skills", "adk_request_confirmation"})  # ADK's own  # the core's tools that need the user's tap (add-ons name their own)
STATIC_INSTRUCTION = IDENTITY + "\n\n" + rules_text(Who(), gated=False)  # the runner replaces this per request with the full prompt


async def source_done(kind: str, ref: str) -> str | None:
    """Close a thread at its source (the SMS ledger's reminder, say): the add-on that owns its kind does it."""
    from odie import addons
    return await addons.source_done(kind, ref)


def vault_tools(store: Store) -> list:
    """The search tools, when a vault folder is set or photos are on (tagged, so a settings change can swap them)."""
    from odie.photos import settings as photos
    from odie.vault import settings
    from odie.vault.tools import make_vault_tools
    tools = make_vault_tools(store) if settings.configured(store) or photos.is_on(store) else []
    for t in tools:
        t._odie_vault = True
    return tools


def signin_tools(store: Store) -> list:
    """browser_sign_in, while signed-in browsing is on and there's a browser (tagged, so the switch can swap it)."""
    from odie.agent.tools.browser import make_signin_tools
    from odie.browser import find
    from odie.signin import state
    tools = make_signin_tools(store) if state.is_on(store) and find.browser_binary() else []
    for t in tools:
        t._odie_signin = True
    return tools


def memory_file() -> MemoryFile:
    s = config.settings
    return MemoryFile(s.memory_file, s.data_dir / "memory.lock", "odie")


def chat_generate_config(store: Store) -> types.GenerateContentConfig:
    """Sampling for chat turns: the Creativity setting's temperature (odie.sampling). The runner sets it again before
    every turn, so a change in Settings counts from the next message. Claude's adapter drops it (Claude sets its own)."""
    return types.GenerateContentConfig(temperature=chat_temperature(store), top_p=CHAT_TOP_P)


def build_agent(store: Store, instruction: str | Callable | None = None,
                memory: MemoryFile | None = None, on_memory_change=None) -> LlmAgent:
    memory = memory or memory_file()

    from odie.agent.tools.browser import make_browser_tools
    from odie.agent.tools.files import make_file_tools
    from odie.agent.tools.media import make_media_tools
    from odie.browser import find, shared
    browser = find.browser_binary() is not None  # the browser capability: tools only when there's a browser to drive
    core = [*make_memory_tools(memory, on_memory_change), make_shell_tool(store=store),
            *make_web_tools(store=store, browser_for=shared if browser else None),
            *make_local_tools(store, config.settings.timezone, source_done=source_done), *make_media_tools(store), *make_file_tools(),
            *(make_browser_tools(store) if browser else [])]
    from odie import addons
    taken = {t.name for t in core} | CORE_NAMES
    for a in addons.active():
        clash = sorted(a.tool_names & taken)
        if clash:  # ADK would advertise both and run the last one: the add-on's tool could never be called
            addons.refuse(a.name, f"tool names clash with the core: {', '.join(clash)}")
    extra = [t for a in addons.active() for t in addons.tools_of(a, store)]
    return LlmAgent(
        name="odie",
        model=model_for(resolve_selection(store, "chat"), think_harder=False),  # swapped per turn by the runner
        instruction=instruction or STATIC_INSTRUCTION,
        tools=[*vault_tools(store), *signin_tools(store), *extra, *core, build_skill_toolset()],
        generate_content_config=chat_generate_config(store),
    )


def __getattr__(name: str):
    if name == "root_agent":
        store = Store(config.settings.db_path)
        store.init_schema()
        return build_agent(store)
    raise AttributeError(name)
