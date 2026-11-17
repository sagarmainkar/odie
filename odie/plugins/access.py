"""Which connected apps (MCP servers in ~/.odie/mcp.json) each one may use: everyday Odie and each personality, so a
business personality can have its own mail app and not everyday Odie's. The switches are Odie's own records, kept in
its database (app_access), not in mcp.json, which stays the user's standard-format file.

A server nobody has switched is on for everyone, so an install that had servers before this is unchanged. A new
personality starts with everyday Odie's switches as they are when it is made. A server added while a personality is
picked is on for that one only (and one added with everyday Odie picked, for Odie only).

Off means off everywhere in that one's threads: the skills catalog its prompt shows leaves the server out
(odie.skills), its skill refuses to load and a call to one of its tools is refused before it runs
(odie.agent.callbacks), and its tools are not listed (odie.plugins.mcp.PluginMcpToolset). Whose a thread is comes from
the thread's own row (personalities.of_session), never from a request. Background work that runs as everyday Odie
(the mail watch) uses only the servers on for Odie."""
from __future__ import annotations

from odie import personalities
from odie.store.db import Store

ODIE = personalities.ODIE

OFF_HERE = ("{app} is switched off for {name}, so it can't be used in this chat. Tell the user it is off for {name} "
            "in Settings → Connected apps.")


def allowed(store: Store, server: str, pid: str) -> bool:
    """Whether this one (ODIE, or a personality's id) may use this server. A server nobody switched is on.
      "home-mail", nobody switched it                  -> True
      "home-mail", switched off for Mira, asking Mira  -> False
      the same, asking everyday Odie                   -> True"""
    row = store.one("select allowed from app_access where server=? and personality=?", (server, pid))
    if row is None:
        return True
    return bool(row["allowed"])


def set_allowed(store: Store, server: str, pid: str, on: bool) -> None:
    store.execute("insert into app_access(server, personality, allowed) values (?,?,?) "
                  "on conflict(server, personality) do update set allowed=excluded.allowed", (server, pid, int(on)))


def off_for(store: Store, pid: str) -> frozenset[str]:
    """The servers switched off for this one: Mira with home-mail off -> {"home-mail"}; nothing off -> {}."""
    rows = store.query("select server from app_access where personality=? and allowed=0", (pid,))
    return frozenset(r["server"] for r in rows)


def allowed_in(store: Store, server: str, session_id: str | None) -> bool:
    """Whether a thread may use this server: its owner's switch (allowed). No thread, or one with no row (a background
    check) -> everyday Odie's switch."""
    return allowed(store, server, personalities.of_session(store, session_id))


def off_in(store: Store, session_id: str | None) -> frozenset[str]:
    """The servers off in this thread: its owner's (off_for)."""
    return off_for(store, personalities.of_session(store, session_id))


def only_one_using(store: Store, server: str, pid: str) -> bool:
    """Whether this one is the only one who may use the server (everyday Odie and every personality asked), so a new
    link for it may replace the old one without taking anyone else's connection away.
      zapier on for everyone, Mira exists, asking Mira or Odie -> False
      zapier added while Mira was picked (hers alone), asking Mira -> True
      no personalities, asking Odie                             -> True (as it always was)"""
    everyone = [ODIE] + [p.id for p in personalities.list_all(store)]
    users = [who for who in everyone if allowed(store, server, who)]
    return users == [pid]


def copy_odies(store: Store, pid: str) -> None:
    """A personality was just made: it starts with everyday Odie's switches as they are now. Only Odie's rows are
    copied; a server Odie never switched is on for both, and stays on for the new one if Odie switches it later."""
    for row in store.query("select server, allowed from app_access where personality=?", (ODIE,)):
        set_allowed(store, row["server"], pid, bool(row["allowed"]))


def added(store: Store, server: str, pid: str) -> None:
    """A server was just added while this one was picked: on for it, off for everyone else (everyday Odie and every
    other personality). Example: work-mail added with Mira picked -> on for Mira; off for Odie and Coach; a
    personality made later copies Odie's (off)."""
    everyone = [ODIE] + [p.id for p in personalities.list_all(store)]
    for who in everyone:
        set_allowed(store, server, who, who == pid)


def forget_server(store: Store, server: str) -> None:
    """The server was removed from mcp.json: its switches go with it."""
    store.execute("delete from app_access where server=?", (server,))


def forget_personality(store: Store, pid: str) -> None:
    """The personality was deleted: its switches go with it."""
    store.execute("delete from app_access where personality=?", (pid,))


def skills_off_in(store: Store, session_id: str | None) -> frozenset[str]:
    """The on-demand skills of the servers off in this thread (mcp-<server>), which its skills catalog leaves out:
    Mira's thread with work-mail off -> {"mcp-work-mail"}."""
    from odie.plugins.mcp import skill_name_of
    return frozenset(skill_name_of(server) for server in off_in(store, session_id))


def server_called(tool_name: str, args: dict) -> str | None:
    """The connected app a tool call reaches, or None when it reaches none: one of the app's own tools, or loading the
    app's skill (which would list its tools).
      echo (a tool of the tester server)  -> "tester"
      load_skill("mcp-tester")            -> "tester"
      load_skill("trackers"), run_shell   -> None"""
    from odie.plugins.mcp import TOOL_SERVER, server_of_skill
    if tool_name == "load_skill":
        return server_of_skill(str((args or {}).get("skill_name") or ""))
    return TOOL_SERVER.get(tool_name)


def refusal(store: Store, tool_name: str, args: dict, session_id: str | None) -> str | None:
    """Why this tool call may not run in this thread, in words for the model, or None when it may. Checked before a
    tool runs (odie.agent.callbacks), so a tool name the model remembers from before the switch went off is still
    refused there.
      echo in Mira's thread, tester off for her          -> "tester is switched off for Mira, so it can't be used…"
      load_skill("mcp-tester") there                     -> the same
      echo in everyday Odie's thread, tester on for Odie -> None
      run_shell, anywhere                                -> None (not a connected app's)"""
    server = server_called(tool_name, args)
    if server is None:
        return None
    owner = personalities.of_session(store, session_id)
    if allowed(store, server, owner):
        return None
    return OFF_HERE.format(app=server, name=_name_of(store, owner))


def _name_of(store: Store, pid: str) -> str:
    """Who a thread belongs to, by name: a personality's, or the name the user gave everyday Odie."""
    found = personalities.get(store, pid)
    if found is not None:
        return found.name
    from odie import persona
    return persona.get(store)["name"]
