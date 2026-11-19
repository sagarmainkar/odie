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
    """Whether a thread may use this server: its owner's switch (allowed).
      work-mail, a thread of Mira's, on for her alone       -> True
      work-mail, an everyday thread ("chat-2026-11-17")     -> False (Odie's switch is off)
      work-mail, no thread or one with no row (a background check) -> False (everyday Odie's switch)"""
    return allowed(store, server, personalities.of_session(store, session_id))


def off_in(store: Store, session_id: str | None) -> frozenset[str]:
    """The servers off in this thread: its owner's (off_for).
      a thread of Mira's, home-mail off for her -> {"home-mail"}
      an everyday thread, nothing off for Odie  -> {}"""
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
    """The server was removed from mcp.json: its switches and its known tool names go with it."""
    store.execute("delete from app_access where server=?", (server,))
    known = known_tools(store)
    if known.pop(server, None) is not None:
        store.set_setting(KNOWN_TOOLS, known)


def forget_personality(store: Store, pid: str) -> None:
    """The personality was deleted: its switches go with it."""
    store.execute("delete from app_access where personality=?", (pid,))


def give_back_to_odie(store: Store, gone: str) -> list[str]:
    """A personality was just deleted (its record is gone, its switches not yet): every server it could use that is off
    for everyday Odie, that no one left may use, and that could clash with no other configured server goes back on for
    Odie. It was off for Odie only because it was the deleted one's, and otherwise nothing could use it. Returns their
    names, for the log.
      work-mail added with Mira picked, Mira deleted, nothing like it configured -> on for Odie again: ["work-mail"]
      coach-app added with Coach picked, Mira deleted, Coach still there      -> left off for Odie
      home-mail Odie switched off for himself, Mira had it off too           -> left off for Odie (it was never hers)
      mail-2 hers, Odie's mail configured (on, failed or switched off)       -> left off for Odie (could_clash); its
                                                                               switch shows"""
    from odie.plugins.mcp import read_config
    configured, _ = read_config()
    known = known_tools(store)
    others = [p.id for p in personalities.list_all(store)]
    every_server = set(configured) | set(known) | _servers_with_switches(store)  # configured or not, known or not
    given_back = []
    for server in sorted(off_for(store, ODIE)):
        was_hers = allowed(store, server, gone)
        someone_uses_it = any(allowed(store, server, who) for who in others)
        if not was_hers or someone_uses_it:
            continue
        like_another = any(could_clash(server, other, configured, known) for other in every_server if other != server)
        if like_another:
            continue
        set_allowed(store, server, ODIE, True)
        given_back.append(server)
    return given_back


def _servers_with_switches(store: Store) -> set[str]:
    """Every server someone has a switch row for, whether or not mcp.json still names it."""
    return {r["server"] for r in store.query("select distinct server from app_access")}


def skills_off_in(store: Store, session_id: str | None) -> frozenset[str]:
    """The on-demand skills of the servers off in this thread (mcp-<server>), which its skills catalog leaves out:
    Mira's thread with work-mail off -> {"mcp-work-mail"}."""
    from odie.plugins.mcp import skill_name_of
    return frozenset(skill_name_of(server) for server in off_in(store, session_id))


def server_of_tool(store: Store, tool_name: str, session_id: str | None) -> str | None:
    """The server a call to this tool reaches in this thread: of the servers that list it, the one on for the thread's
    owner. Two connections of one service list the same names, and each owner has at most one of them on
    (load_servers), so a name resolves to the owner's own connection. When none is on for the owner, the first one,
    so the call is refused as off. None for a tool no server lists.
      send_email in everyday Odie's thread, home mail (mail) his, work mail (mail-2) Mira's -> "mail"
      send_email in Mira's thread                                                          -> "mail-2"
      send_email in Odie's thread, both off for him                                        -> "mail" (refused as off)
      run_shell                                                                            -> None"""
    from odie.plugins.mcp import servers_with_tool
    candidates = servers_with_tool(tool_name)
    if not candidates:
        return None
    owner = personalities.of_session(store, session_id)
    for server in candidates:
        if allowed(store, server, owner):
            return server
    return candidates[0]


def app_title_of_tool(store: Store, tool_name: str, session_id: str | None) -> str | None:
    """The title of the app a call to this tool reaches in this thread, for its approval card and hints: send_email in
    Mira's thread -> "Work mail"; in Odie's -> "Home mail"; a tool of no app -> None. A tool named only in the older
    one-app-per-tool map (TOOL_APP, which tests fill by hand) keeps that title."""
    from odie.plugins.mcp import SERVER_TITLE, TOOL_APP
    server = server_of_tool(store, tool_name, session_id)
    if server is None:
        return TOOL_APP.get(tool_name)
    return SERVER_TITLE.get(server, server)


def skill_of_tool(store: Store, tool_name: str, session_id: str | None) -> str | None:
    """The skill that brings this tool in this thread: send_email in Mira's thread -> "mcp-mail-2"; in Odie's ->
    "mcp-mail"; an always-on app's tool, or a tool of no app -> None (the older map, TOOL_SKILL, for a tool only it
    names)."""
    from odie.plugins.mcp import SERVER_SKILL, TOOL_SKILL
    server = server_of_tool(store, tool_name, session_id)
    if server is None:
        return TOOL_SKILL.get(tool_name)
    return SERVER_SKILL.get(server)


def server_of_object(store: Store, tool, session_id: str | None) -> str | None:
    """The server a tool OBJECT reaches when it runs: the name its toolset stamped on it (PluginMcpToolset), which is
    what ADK will call whatever the switches say now; only an object with no stamp (a built-in, a test's stand-in) is
    looked up by its name (server_of_tool).
      the send_email object home mail's toolset listed, home mail since switched off -> "mail" (it would still reach it)
      run_shell                                                                     -> None"""
    stamped = getattr(tool, "_odie_server", None)
    if stamped:
        return stamped
    return server_of_tool(store, tool.name, session_id)


def server_called(store: Store, tool, args: dict, session_id: str | None) -> str | None:
    """The connected app a tool call reaches, or None when it reaches none: one of the app's own tools (the server its
    object came from, server_of_object), or loading the app's skill (which would list its tools).
      echo (listed by the tester server)  -> "tester"
      load_skill("mcp-tester")            -> "tester"
      load_skill("trackers"), run_shell   -> None
      load_skill with no skill_name       -> None"""
    from odie.plugins.mcp import server_of_skill
    if tool.name != "load_skill":
        return server_of_object(store, tool, session_id)
    if not args:
        return None
    skill = args.get("skill_name")
    if not isinstance(skill, str):
        return None
    return server_of_skill(skill)


def refusal(store: Store, tool, args: dict, session_id: str | None) -> str | None:
    """Why this tool call may not run in this thread, in words for the model, or None when it may. Checked before a
    tool runs (odie.agent.callbacks), on the object about to run, so a tool listed before a switch went off, or a name
    the model remembers, is still refused there.
      echo in Mira's thread, tester off for her             -> "tester is switched off for Mira, so it can't be used…"
      load_skill("mcp-tester") there                        -> the same
      echo in everyday Odie's thread, tester on for Odie    -> None
      send_email listed from home mail, home mail since switched off for Odie (work mail on) -> refused, naming mail
      run_shell, anywhere                                   -> None (not a connected app's)"""
    server = server_called(store, tool, args, session_id)
    if server is None:
        return None
    owner = personalities.of_session(store, session_id)
    if allowed(store, server, owner):
        return None
    return OFF_HERE.format(app=server, name=_name_of(store, owner))


LAPSED = "This card was for {app}, which is now off for {name}. Ask again."


def card_moved(store: Store, card) -> str | None:
    """Why a tapped card may not run, in words, or None when it may: a tap is consent for the account the card named,
    so the card's server must still be on for the thread's owner. `card` is its approvals row; its detail says the
    server ("server") and the app's title ("app") the card showed.
      "Send email in Home mail" (mail), mail still on for Odie        -> None
      the same, the owner since moved Odie to work mail (mail-2)      -> "This card was for Home mail, which is now off for
                                                                         Odie. Ask again."
      a card for no app (run_shell)                                   -> None"""
    import json
    detail = json.loads(card["detail_json"] or "{}")
    server = detail.get("server")
    if not server:
        return None
    owner = personalities.of_session(store, card["session_id"])
    if allowed(store, server, owner):
        return None
    app = detail.get("app") or server
    return LAPSED.format(app=app, name=_name_of(store, owner))


def card_runs_elsewhere(store: Store, card, tool, session_id: str | None) -> str | None:
    """Why the object a tapped card is about to run may not run, in words, or None when it may: it must reach the very
    server the card named, still on for the owner (card_moved).
      the card named mail; the object is home mail's                -> None
      the card named mail; the object is work mail's (mail-2)       -> the card's words: "This card was for Home mail…"
      a card that named no server                                   -> None"""
    import json
    moved = card_moved(store, card)
    if moved:
        return moved
    detail = json.loads(card["detail_json"] or "{}")
    named = detail.get("server")
    if not named:
        return None
    reaches = server_of_object(store, tool, session_id)
    if reaches == named:
        return None
    owner = personalities.of_session(store, session_id)
    return LAPSED.format(app=detail.get("app") or named, name=_name_of(store, owner))


def no_one_has_both(store: Store, first: str, second: str) -> bool:
    """Whether two servers may list the same tool names: no one (everyday Odie, or any personality) has both on.
      mail on for Odie alone, mail-2 on for Mira alone -> True: both load
      both on for Odie (nobody switched anything)      -> False: the second is refused, as before personalities"""
    everyone = [ODIE] + [p.id for p in personalities.list_all(store)]
    return not any(allowed(store, first, who) and allowed(store, second, who) for who in everyone)


TAKEN = "{name} already has these tools from '{other}'; switch that one off for {name} first."
KNOWN_TOOLS = "mcp.known_tools"  # server -> the tool names it listed last time it listed any


def remember_tools(store: Store, listed: dict[str, list[str]]) -> None:
    """Keep each server's tool names from a load where it listed some. A server that failed to list or is switched
    off keeps the names it listed before, so a clash with it can still be seen (clash_for)."""
    known = dict(store.get_setting(KNOWN_TOOLS) or {})
    for server, tools in listed.items():
        if tools:
            known[server] = list(tools)
    store.set_setting(KNOWN_TOOLS, known)


def known_tools(store: Store) -> dict[str, list[str]]:
    return dict(store.get_setting(KNOWN_TOOLS) or {})


def _host(spec: dict) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(str(spec.get("url") or "")).hostname or "").lower()


def same_service(first: dict, second: dict) -> bool:
    """Whether two servers' specs look like two connections of one service, for when nothing is known of their tools:
    the same preset, the same title, the same link's host, or the same program (_program). Only servers different in
    all of those count as different services.
      two Zapier links                                    -> True
      https://mail.example.invalid/home and …/work        -> True (the same host)
      "Home mail" and "Work mail", one program, two envs  -> True (the same program)
      uvx mail-mcp --account home / --account work        -> True (the same program, other flags)
      a mail server and a notes server, nothing in common -> False"""
    from odie.plugins.presets import preset_of
    first_preset = preset_of(str(first.get("url") or ""))
    if first_preset is not None and first_preset == preset_of(str(second.get("url") or "")):
        return True
    first_title = str(first.get("title") or "").strip().casefold()
    if first_title and first_title == str(second.get("title") or "").strip().casefold():
        return True
    if _host(first) and _host(first) == _host(second):
        return True
    return _program(first) is not None and _program(first) == _program(second)


def _program(spec: dict) -> tuple[str, str] | None:
    """What a command-line server runs: its command's name and its first argument that isn't a flag (the package or
    script), so two accounts of one program, which differ only in flags or env, are the same program.
      uvx mail-mcp --account home              -> ("uvx", "mail-mcp")
      python3 /path/mail.py                    -> ("python3", "/path/mail.py")
      a server reached by a link (no command)  -> None"""
    from pathlib import PurePath
    command = str(spec.get("command") or "")
    if not command:
        return None
    first_plain = next((str(a) for a in spec.get("args") or [] if not str(a).startswith("-")), "")
    return PurePath(command).name, first_plain


def could_clash(first: str, second: str, configured: dict[str, dict], known: dict[str, list[str]]) -> bool:
    """Whether two servers could list the same tool names: by the names they last listed when both are known, else
    by looking like one service (same_service), so an unknown is never taken for "no clash".
      mail and mail-2, both listed send_email          -> True
      mail and notes, both known, nothing in common    -> False
      mail failed to list ever, mail-2 the same host   -> True
      a server with no known tools and no spec at all  -> True (nothing to tell them apart by)"""
    first_tools, second_tools = set(known.get(first) or ()), set(known.get(second) or ())
    if first_tools and second_tools:
        return bool(first_tools & second_tools)
    first_spec, second_spec = configured.get(first) or {}, configured.get(second) or {}
    nothing_known = (not first_tools and not first_spec) or (not second_tools and not second_spec)
    if nothing_known:
        return True  # no tools and no spec to compare: it could be anything, so it counts as a clash
    return same_service(first_spec, second_spec)


def clash_for(store: Store, server: str, pid: str, configured: dict[str, dict]) -> str | None:
    """Why this server can't be switched on for this one, in words, or None when it can: another configured server on
    for it could list the same tool names (could_clash: the last known names, else the same service), and each owner
    has one connection of a service at a time. `configured`: mcp.json's servers.
      mail on for Mira, while mail-2 (the same tools) is on for her
                           -> "Mira already has these tools from 'mail-2'; switch that one off for Mira first."
      the same, mail-2 failed at the last load but listed them before -> the same words
      mail on for Mira, mail-2 off for her, or nothing in common       -> None"""
    clashing = clashing_with(store, server, pid, configured)
    if not clashing:
        return None
    return TAKEN.format(name=_name_of(store, pid), other=clashing[0])


def clashing_with(store: Store, server: str, pid: str, configured: dict[str, dict]) -> list[str]:
    """The other configured servers on for this one that could list this server's tool names (could_clash).
      work-mail just added for Mira, home mail still on for her -> ["mail"]
      nothing like it on for her                               -> []"""
    known = known_tools(store)
    found = []
    for other in configured:
        if other == server or not allowed(store, other, pid):
            continue
        if could_clash(server, other, configured, known):
            found.append(other)
    return found


SWITCHED_FOR_IT = "{others} is now off for {name}, so {name} uses {added} instead."


def make_room_for(store: Store, added_server: str, pid: str, configured: dict[str, dict]) -> str | None:
    """A personality just added a server of its own: switch off for it the servers on for it that the new one could
    clash with (each owner has one connection of a service at a time), and say so, or None when nothing was in the way.
    Only for a personality: a server added with everyday Odie picked never switches his own off.
      work-mail added with Mira picked, home mail on for her -> home mail off for her;
                                                               "mail is now off for Mira, so Mira uses work-mail instead."
      notes added with Mira picked, nothing like it         -> None"""
    if pid == ODIE:
        return None
    in_the_way = clashing_with(store, added_server, pid, configured)
    if not in_the_way:
        return None
    for other in in_the_way:
        set_allowed(store, other, pid, False)
    return SWITCHED_FOR_IT.format(others=", ".join(in_the_way), name=_name_of(store, pid), added=added_server)

def _name_of(store: Store, pid: str) -> str:
    """Who a thread belongs to, by name: a personality's, or the name the user gave everyday Odie."""
    found = personalities.get(store, pid)
    if found is not None:
        return found.name
    from odie import persona
    return persona.get(store)["name"]
