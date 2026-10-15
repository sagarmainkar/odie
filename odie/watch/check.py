"""One watch check (spec parts 2 and 3): find the sources when they're stale, run the watcher's turn with its five
tools and the user's Watch for entries, then apply the report (card, pushes, posts) or, without one, a card written by
code. Sources that just failed three times in a row, or just came back, are said once."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from odie.watch import report as rep
from odie.watch import sources
from odie.watch.fetch import STATE, Fetcher
from odie.watch.tools import Check, watch_tools

log = logging.getLogger("odie.watch")
INTERVAL = timedelta(minutes=30)
SKILL = Path(__file__).parent / "skill" / "SKILL.md"
WATCH_FOR = "Watch for"


def due(store, now: datetime) -> bool:
    """Is a watch check due? Yes when there has been none (or its time is unreadable), or INTERVAL has passed.
    Example: last check 09:00 -> False at 09:20, True at 09:30; never checked -> True."""
    last = (store.get_setting(STATE) or {}).get("last_check")
    if not last:
        return True
    try:
        return now - datetime.fromisoformat(last) >= INTERVAL
    except ValueError:
        return True


def watch_for(memory) -> str:
    try:
        topic = memory.load().topic(WATCH_FOR)
    except Exception:  # noqa: BLE001 (no memory file yet)
        return ""
    if topic is None or not topic.entries:
        return ""
    return "\n".join(f"- {e.title}: {e.body.strip()}" for e in topic.entries[:30])


def guard(tool, args, tool_context) -> dict | None:
    """before_tool_callback for the watch's turn: what a background check refuses (odie.trackers.guard), and also
    changing memory, the shell, handing files over, closing tasks and the browser.
    Example: new_mail -> None (runs); update_memory -> refused; browser_open -> refused (the browser keeps signed-in
    sites); task_update -> refused (tasks are the user's to close)."""
    from odie.trackers import guard as trackers_guard
    refused = trackers_guard(tool, args, tool_context)
    if refused:
        return refused
    not_for_the_watch = tool.name in ("update_memory", "forget_memory", "run_shell", "hand_over", "task_update")
    is_browser = tool.name.startswith("browser_")
    if not_for_the_watch or is_browser:
        return {"error": "Not allowed in the background watch: report it as a needs-you item instead."}
    return None


def _instruction(memory_text: str, watch: str) -> str:
    body = SKILL.read_text().split("---", 2)[-1].strip()
    return (f"{body}\n\n## Watch for\n{watch or '(nothing yet)'}\n\n## What you remember about the user\n{memory_text or '(nothing)'}")


async def run_check(store, now: datetime, turn, post, push, memory=None, memory_index: str = "") -> str:
    if sources.stale(store, now):
        await sources.detect_and_save(store)
    if not sources.saved(store):
        store.set_setting(rep.CARD, {"checked_at": now.isoformat(timespec="seconds"), "line": "", "needs_you": [], "events": [],
                                     "sources": {}, "off": "Connect Gmail and Calendar (Zapier, Composio or another app) to see them here."})
        return "off"
    check = Check(Fetcher(store, now))
    tools = watch_tools(check)
    instruction = _instruction(memory_index, watch_for(memory) if memory is not None else "")
    prompt = "Run the watch check."  # the background turn puts the time before it (odie.app.runner.background_turn)
    reason = ""
    try:
        await turn(prompt, tools, instruction)
    except Exception as e:  # noqa: BLE001 (a failed turn still leaves a card)
        reason = f"{type(e).__name__}: {e}"[:160]
        log.warning("watch turn failed", exc_info=True)
    fetcher = check.fetcher
    if not check.read:  # the model never looked: read once, for the nudge and for the card's counts
        check.mails = await fetcher.new_mail()
        check.events = await fetcher.upcoming_events()
        check.read = True
    if check.report is None:  # small models often stop short of report: one nudge, with what the check read
        nudge = ("You ended the watch check without calling report. This is what the check read; call report now "
                 "(an empty needs_you list when nothing needs the user, and a one-sentence line for Today).\n"
                 f"Mail: {json.dumps([check.fenced(m) for m in check.mails], ensure_ascii=False)}\n"
                 f"Events: {json.dumps([e.brief() for e in check.events], ensure_ascii=False)}")
        try:
            await turn(nudge, tools, instruction)
        except Exception as e:  # noqa: BLE001
            reason = f"{type(e).__name__}: {e}"[:160]
            log.warning("watch nudge failed", exc_info=True)
    first = bool(fetcher.first)
    failing = rep.failing_now(store, fetcher.statuses)  # read against the last check, so before commit()
    recovered = rep.recovered_now(store, fetcher.statuses)
    r = check.report
    to_push: list[dict] = []
    try:
        if r is None:
            rep.fallback(store, now, check.mails, check.events, fetcher.statuses, reason or "no report from the model")
        else:
            to_push = rep.apply(store, now, r["needs_you"], r["line"], check.mails, check.events, fetcher.statuses, first)
    finally:
        fetcher.commit()  # the check's place is saved first: a post that fails never makes it run again every 5 minutes

    async def say(text: str, media=None) -> None:
        try:
            await post(text, media=media)
        except Exception:  # noqa: BLE001
            log.warning("watch: a message couldn't be posted", exc_info=True)

    def ping(title: str, body: str) -> None:
        try:
            push(title, body)
        except Exception:  # noqa: BLE001
            log.warning("watch: a push failed", exc_info=True)
    for app in failing:
        await say(f"{app} stopped working for the watch. Fix it in Settings → Connected apps.")
        ping(f"{app} stopped working", "Fix it in Settings → Connected apps.")
    for app in recovered:
        await say(f"{app} works again: the watch is back.")
    if r is None:
        return "fallback"
    for it in to_push:
        ping(it["title"], it["why"])
    from odie.agent.tools.files import hand_over, workspace
    ws = workspace().resolve()
    for d in r["done"]:
        media = []
        files = d.get("files") or []
        for x in files:
            if not x:
                continue
            f = Path(x).resolve()
            if f.is_file() and ws in f.parents:  # only files in Odie's workspace become download cards
                got = hand_over(f, f.name)
                if "media" in got:
                    media.append(got["media"])
        await say(str(d.get("message") or "Done.")[:500], media=media or None)
        ping("Odie: done", str(d.get("message") or "")[:160])
    return "ok"
