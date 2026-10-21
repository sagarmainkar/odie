"""Built-in skills: each folder holds a SKILL.md (what it's for, how to use it) and, optionally, a tools module. The
catalog (name + one line each) goes into the system prompt; load_skill brings a skill's instructions.

Odie's own skills' tools (trackers, stocks, documents, skill-builder, about-odie, a user's trusted skills) are declared
from the first request of a conversation on, loaded or not (2026-10-12). They used to join the tool list when the skill
loaded and leave at the next turn, and each change of the tool list made the model read the whole prompt again (0%
reusable, twice, for one trackers question on GLM). They cost ~2.2k tokens, paid once: after the first request they
come from the provider's cache.

A connected app's tools (an MCP server's: Gmail and Calendar, the Obsidian vault) are different: there are many of them
(19 for those two apps, ~3.1k tokens on Gemma) and most chats never use them. Declared from the start, they made local
Gemma's first request 53 tools long, and it stopped drawing blocks (chat of 12 Oct). So they join when the model loads the
app's skill (mcp-gmail-calendar…) and then stay for the rest of the chat: the tool list changes at most once per app
per chat, and every other request still starts with the one before. Which skills are loaded is kept in the session's
state, so a chat keeps its apps' tools after a restart."""
import asyncio
import logging

from google.adk.features import FeatureName, override_feature_enabled
from google.adk.tools.skill_toolset import SkillDiscoveryMode, SkillToolset

from odie import config

log = logging.getLogger("odie.skills")


class FixedToolsSkillToolset(SkillToolset):
    """ADK's SkillToolset, with Odie's tool list: every skill's own tools on every request, in the order they were given,
    then each loaded app's tools, in the order the apps were loaded (an app's in the order its server lists them), so a
    newly loaded app only adds at the end. A tool whose name the toolset already has (load_skill…, or an earlier
    skill's) is left out, as ADK does."""

    async def _resolve_additional_tools_from_state(self, readonly_context):
        tools = list(self._provided_tools_by_name.values())
        tools += await self._loaded_apps_tools(readonly_context)
        taken = {t.name for t in self._tools}
        out = []
        for t in tools:
            if t.name not in taken:
                taken.add(t.name)
                out.append(t)
        return out

    async def _loaded_apps_tools(self, readonly_context) -> list:
        """The tools of every app whose skill this chat has loaded, in loading order. Worked example, with the Gmail and
        Calendar app and the vault app connected:
          a fresh chat                                        -> []
          after load_skill("mcp-obsidian-vault")              -> [index_status, read_note, related_notes, search_notes]
          two turns later, after load_skill("mcp-gmail-calendar") -> the vault's four, then Gmail and Calendar's 15
          the same chat after a restart                      -> the same 19 (the loaded skills are in the session's state)"""
        if readonly_context is None or not self._provided_toolsets:
            return []
        loaded = self._active_skills(readonly_context.state, readonly_context.agent_name, readonly_context.invocation_id)
        wanted: list[str] = []
        for name in loaded:
            skill = await self._get_or_fetch_skill(name, readonly_context.invocation_id)
            if skill is not None:
                wanted += skill.frontmatter.metadata.get("adk_additional_tools") or []
        if not wanted:
            return []
        listed = await asyncio.gather(*(ts.get_tools_with_prefix(readonly_context) for ts in self._provided_toolsets),
                                      return_exceptions=True)
        by_name = {}
        for got in listed:
            if isinstance(got, Exception):  # an app that can't list its tools right now: the others still come
                log.warning("an app's tools couldn't be listed: %s", got)
                continue
            if isinstance(got, BaseException):
                raise got
            for t in got:
                by_name.setdefault(t.name, t)
        return [by_name[n] for n in wanted if n in by_name]


def loaded_skills_state(agent_name: str, skills) -> dict:
    """Session state in which these skills count as already loaded for the agent (ADK keeps their names under
    "_adk_activated_skill_<agent>"), so their apps' tools are there from the first request without a load_skill.
    ("odie_tracker", ["mcp-gmail-calendar"]) -> {"_adk_activated_skill_odie_tracker": ["mcp-gmail-calendar"]};
    no skills -> {}."""
    names = list(skills or ())
    if not names:
        return {}
    return {f"_adk_activated_skill_{agent_name}": names}


def build_skill_toolset(entries=None, extra_skills=(), extra_tools=()) -> SkillToolset:
    """One toolset for every usable skill (plus synthetic ones, e.g. MCP servers): the catalog goes into the prompt,
    every skill's own tools are declared all the time, and an app's from the moment its skill loads
    (FixedToolsSkillToolset)."""
    if entries is None:
        from odie.skills.registry import discover
        from odie.store.db import Store
        store = Store(config.settings.data_dir / "assistant.db")
        store.init_schema()  # idempotent; a fresh data dir has no tables yet
        entries = discover(store)
    ok = [e for e in entries if e.status == "ok"]
    # No lifecycle: a loaded skill is never released, so ADK never rewrites its instructions out of the history (which
    # would change what the model has already read), there's no unload_skill (a model unloaded a skill before
    # writing the answer it was for), and an app's tools stay once its skill has loaded them.
    override_feature_enabled(FeatureName.SKILL_LIFECYCLE, False)
    return FixedToolsSkillToolset(
        [e.skill for e in ok] + list(extra_skills),
        additional_tools=[t for e in ok for t in e.tool_objs] + list(extra_tools),
        discovery_mode=SkillDiscoveryMode.EAGER,
        tool_filter=lambda tool, ctx=None: tool.name not in ("run_skill_script", "unload_skill"),
    )
