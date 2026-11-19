"""The chat agent's tools for Workers: start a job, see the jobs, stop one, retry one, clear a failed one's card.
Their docstrings are the model's guidance on when a job is for a Worker and when the chat should just answer. Each
works on the jobs of whoever the chat belongs to (everyday Odie or a personality), never another's."""
from __future__ import annotations

import os
import re
from pathlib import Path

from google.adk.tools import FunctionTool, ToolContext

from odie.agent.context import session_id_of
from odie.store.db import Store
from odie.workers import router
from odie.workers import store as jobs

ONLY_IN_CHAT = "Jobs start only from a chat with the user."
BRIEF_MOST = 8000
PRIVATE = ("Not started: this chat read your signed-in {sites}, and a background job can't keep that private. Start "
           "it in a new chat, without the signed-in pages.")
WEB_TOOLS = frozenset({"web_fetch", "web_search"})


def job_line(j: dict) -> str:
    """One line for a job in jobs_status: "job-3f9a2c · running · Tides report (10:42)" (the time in UTC, as stored)."""
    when = (j.get("ended_at") or j.get("started_at") or j.get("created_at") or "")[11:16]
    line = f"{j['id']} · {j['status']} · {j['title']}"
    if when:
        line += f" ({when})"
    return line


def chat_of(tool_context) -> str | None:
    """The chat thread a tool call came from, or None when it isn't a chat (a background check, the watch): "chat-
    2026-11-18" -> itself; a watch turn's throwaway session -> None. So nothing in the background starts a job."""
    from odie import threads
    sid = session_id_of(tool_context)
    if not threads.valid_id(sid or ""):
        return None
    return sid


def owner_of(store: Store, tool_context) -> str:
    from odie import personalities
    return personalities.of_session(store, session_id_of(tool_context))


def private_sites(store: Store, session_id: str) -> set:
    """The signed-in sites this chat (or this turn) has read: a job started from it could carry their words out."""
    from odie.agent import turn
    from odie.signin import guard as signin_guard
    sites = signin_guard.private_of(store, session_id) | turn.private_sites()
    if not sites or not signin_guard._on(store):
        return set()
    return sites


def calls_this_turn(tool_context) -> list[str]:
    """The tools the model called in this turn before this one (read from the turn's own events)."""
    from odie.agent.context import parts_of
    session = getattr(tool_context, "session", None)
    invocation = getattr(tool_context, "invocation_id", None)
    names = []
    for event in getattr(session, "events", None) or []:
        if invocation is None or getattr(event, "invocation_id", None) != invocation:
            continue
        for part in parts_of(event):
            call = getattr(part, "function_call", None)
            if call is not None and call.name:
                names.append(call.name)
    return names


def taint_of(store: Store, tool_context) -> str:
    """What outside text this chat has read, this turn or any earlier one, when it starts a job, or "" when none: the
    job's brief is then built from his own typed words only (brief_for). odie.workers.taint keeps it for the chat.
      the chat read mail or messages (other people's words), now or turns ago -> "mail"
      it fetched or searched the web, or used the browser                     -> "web pages"
      it called a connected app's tool                                        -> "an app"
      it read only notes or memory, or nothing (a new chat)                   -> "" """
    from odie.agent import turn
    from odie.plugins import access
    from odie.workers import taint as job_taint
    earlier = job_taint.of_chat(store, session_id_of(tool_context))
    if earlier:
        return earlier
    read = turn.read_sources()
    if "your mail" in read or "your messages" in read:
        return "mail"
    called = calls_this_turn(tool_context)
    if any(name in WEB_TOOLS or name.startswith("browser_") for name in called):
        return "web pages"
    app_tools = {name for names in access.known_tools(store).values() for name in names}
    if any(name in app_tools for name in called):
        return "an app"
    return ""


TYPED_MOST = 3  # his last messages handed to a Worker from a chat that read outside text
TYPED_CHARS = 500  # of each: what the audit log keeps of a message (odie.store.db.Store.audit)
ASKED = "The user asked:"
OWN_WORDS_ONLY = ("(This chat had read outside text, so only the user's own messages are handed over, newest last. "
                  "Work from them and the web.)")


def sent_from_terminal(args_json: str | None) -> bool:
    """Whether a recorded message of his was sent by a program from the terminal (odie chat), not typed in an app:
    '{"via": "terminal"}' -> True;  None (typed or dictated in an app) -> False;  anything unreadable -> False."""
    import json
    try:
        args = json.loads(args_json or "null")
    except ValueError:
        return False
    return isinstance(args, dict) and args.get("via") == "terminal"


def typed_words(store: Store, session_id: str) -> list[str]:
    """His own last messages in this chat, newest last: what he typed or dictated, as the runner recorded each turn
    before anything ran (the audit log: actor "user", event "message"). Never Odie's replies, a tool's answer or a
    job's report (those are "agent" rows), nor a message a program sent from the terminal (odie chat: marked "via
    terminal"). At most TYPED_MOST, each cut to TYPED_CHARS; a form's answer as its line only.
      he said "first", "second", "third", "fourth"           -> ["second", "third", "fourth"]
      he said "a", the terminal sent "b", he said "c"        -> ["a", "c"]
      a new chat, or only the terminal spoke                 -> []"""
    from odie.blocks.answers import without_form_answers
    rows = store.query("select result_summary, args_json from audit_log where session_id=? and actor='user' and "
                       "event='message' order by id desc limit 30", (session_id,))
    newest_first = []
    for row in rows:
        if sent_from_terminal(row["args_json"]):
            continue
        text = without_form_answers(row["result_summary"] or "")
        if not text:
            continue
        newest_first.append(text[:TYPED_CHARS])
        if len(newest_first) == TYPED_MOST:
            break
    return list(reversed(newest_first))


def brief_for(model_brief: str, typed: list[str], taint: str) -> str | None:
    """The brief the Worker gets. When the chat has read outside text (taint), only his own typed words, built here by
    code, so nothing a mail or a page said can ride along in it; the model's brief is dropped. A clean chat: the
    model's brief, with his newest message first so the Worker sees what he actually asked. None when the chat is
    tainted and nothing he typed is there to hand over (the job isn't started).
      tainted, typed ["read Asha's mail", "now research it"]  -> "The user asked:\nread Asha's mail\n\nnow research it\n\n(…)"
      clean, typed ["older", "try example/app"], brief "Clone it…" -> "The user asked:\ntry example/app\n\nClone it…"
      clean, nothing typed found, brief "Clone it…"           -> "Clone it…"
      tainted, nothing typed found                            -> None"""
    if taint:
        if not typed:
            return None
        return f"{ASKED}\n" + "\n\n".join(typed) + f"\n\n{OWN_WORDS_ONLY}"
    if not typed:
        return model_brief
    return f"{ASKED}\n{typed[-1]}\n\n{model_brief}"


READ_DIRS_MOST = 3


def odie_places() -> list[Path]:
    from odie import config
    places = [config.settings.data_dir, config.settings.config_dir, Path.home() / ".odie"]
    named = os.environ.get("ODIE_HOME")
    if named:
        places.append(Path(named).expanduser())
    return [Path(p).expanduser().resolve() for p in places]


def true_path(path: Path) -> Path:
    """The path as it is on disk, links followed and in its real case (macOS's disk ignores case: ~/library is
    ~/Library). F_GETPATH on an open descriptor gives that; resolve() is the fallback (third review, 19 Nov 2026)."""
    import fcntl
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return path.resolve()
    try:
        raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
        return Path(raw.split(b"\0", 1)[0].decode())
    except (OSError, AttributeError):
        return path.resolve()
    finally:
        os.close(fd)


def same_or_inside(a: Path, b: Path) -> bool:
    """Whether a is b or inside it, ignoring case as the disk does."""
    a_parts = [p.casefold() for p in a.parts]
    b_parts = [p.casefold() for p in b.parts]
    return a_parts[: len(b_parts)] == b_parts


def overlaps(a: Path, b: Path) -> bool:
    return same_or_inside(a, b) or same_or_inside(b, a)


QUOTED_PATH = re.compile(r"[\"'`]([~/][^\"'`]+)[\"'`]")
BARE_PATH = re.compile(r"(?<![\w/~])([~/][^\s\"'`,;:!?()<>\[\]{}]*)")


def expand(given: str) -> Path:
    if given == "~" or given.startswith("~/"):
        return Path.home() / given[2:]
    return Path(given)


def folders_named(words: str | None) -> list[Path]:
    """The folders his words name, each as a whole path (quoted, or bounded by spaces and punctuation), in its real
    form on disk; a path with ".." in it, or one that is a file or doesn't exist, names nothing.
      'please test ~/work/app.' -> [<home>/work/app];  'read ~/Documents/c.txt' -> [] (a file);
      '"~/library/Application Support/Odie"' -> [<home>/Library/Application Support/Odie] (its real case)"""
    if not words:
        return []
    found = [m.group(1) for m in QUOTED_PATH.finditer(words)]
    found += [m.group(1).rstrip(".") for m in BARE_PATH.finditer(words)]
    out = []
    for text in found:
        if ".." in Path(text).parts:
            continue
        path = expand(text.rstrip("/"))
        if path.is_absolute() and path.is_dir():
            out.append(true_path(path))
    return out


def named_by_user(given: str, folder: Path, words: str | None) -> bool:
    """Whether the user's own words this turn name exactly this folder: a whole path of his, never a shorter part of
    one, never a file's folder, compared as the disk does (real path, case ignored).
      "please test ~/work/app" and ~/work/app -> True;  and ~/work -> False (a prefix);  and ~/work/app/.. -> False;
      "read ~/Documents/c.txt" and ~/Documents -> False (a file names nothing)"""
    wanted = [p.casefold() for p in folder.parts]
    return any([p.casefold() for p in named.parts] == wanted for named in folders_named(words))


def not_his_own(folder: Path) -> str:
    """Why a folder (in its real form on disk) is not one of his own that a job may read or a result may be kept in,
    or "" when it is: a folder under the home (not the home itself), with no hidden part and not in Library (in any
    case), apart from Odie's own folders (not inside them, not around them).
      <home>/work/app -> "";  <home>/.ssh, <home>/library/x -> "hidden or app data…";  <home>, /etc -> "not a folder
      under your home";  Odie's data folder -> "Odie's own folders…" """
    home = true_path(Path.home())
    if not same_or_inside(folder, home) or len(folder.parts) == len(home.parts):
        return "not a folder under your home"
    parts = folder.parts[len(home.parts):]
    if any(part.startswith(".") for part in parts) or parts[0].casefold() == "library":
        return "hidden or app data, never readable by a job"
    if any(overlaps(folder, true_path(place)) for place in odie_places()):
        return "Odie's own folders, never readable by a job"
    return ""


def readable_dir(given: str, words: str | None) -> tuple[str | None, str]:
    """A folder of his a job may read, checked by code: (its real path, "") or (None, why not). It must be one of his
    own (not_his_own) and named by the user as a whole path in these words.
      "~/work/app", said in the request          -> ("/Users/me/work/app", "")
      "~/.ssh", "~/Library/Mail", "~/library/x"  -> (None, "hidden or app data")
      "~" or "/etc"                              -> (None, "not a folder under your home")
      "~/work/app", never said by the user       -> (None, "you didn't name it")"""
    path = expand(given)
    if not path.is_absolute():
        return None, f"{given}: give the folder's whole path"
    if ".." in path.parts:
        return None, f"{given}: give the folder's own path, without .."
    if not path.is_dir():
        return None, f"{given}: no such folder"
    folder = true_path(path)
    why = not_his_own(folder)
    if why:
        return None, f"{given}: {why}"
    if not named_by_user(given, folder, words):
        return None, f"{given}: you didn't name it in your request"
    return str(folder), ""


def keep_place(typed: list[str]) -> str:
    """The folder of his a job's result may be kept in (the card's "Keep it in …"), found by code in his own typed
    words, newest message first, the first folder named there: a real folder of his own, written as a whole path
    (readable_dir's checks), or "" when he named none (then no button; the report says where the result is).
      ["can we try https://github.com/example/app.git in ~/code/demos/"] -> "<home>/code/demos"
      ["put it in ~/code/demos", "go ahead"]                             -> "<home>/code/demos" (said earlier)
      ["try example/app"], ["keep it in ~/.ssh"], ["keep it in /etc"] -> "" (no button)"""
    for words in reversed(typed):
        for folder in folders_named(words):
            found, _ = readable_dir(str(folder), words)
            if found is not None:
                return found
    return ""


MAIL_WORDS = re.compile(r"\b(e-?mails?|mail|inbox|gmail|outlook)\b", re.I)
CALENDAR_WORDS = re.compile(r"\b(calendar|meetings?|appointments?)\b", re.I)


def uses_for(words: str | None, app_names: list[str]) -> str:
    """What a job may reach besides its own folder and the folders he named: always the web, and his apps only when his
    own words this turn ask about them (simpler Workers, 19 Nov 2026), decided by code, never by the model.
      "research e-bikes", "count the lines in ~/work/app"    -> "web"
      "check my mail for the invoice", "my inbox"            -> "apps:mail" (the web and his mail)
      "list my meetings", "my calendar"                      -> "apps:calendar" (the web and his calendar)
      a connected app named as a word ("use notion to …")    -> "app:notion" (the web and that app)"""
    text = words or ""
    if MAIL_WORDS.search(text):
        return "apps:mail"
    if CALENDAR_WORDS.search(text):
        return "apps:calendar"
    for name in app_names:
        if name and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I):
            return f"app:{name}"
    return "web"


def uses_words(uses: str) -> str:
    """What a job uses, as its card says it: "web" -> "the web"; "apps:mail" -> "the web and your mail"; "app:notion"
    -> "the web and notion". An older job's row (started before 19 Nov 2026) as it was: "folder" -> "the folders you
    named, no web"; "none" -> "nothing outside its folder"."""
    if uses == "web":
        return "the web"
    if uses.startswith("app:"):
        return f"the web and {uses[len('app:'):]}"
    if uses.startswith("apps"):
        what = {"apps:mail": "your mail", "apps:calendar": "your calendar"}.get(uses, "your apps")
        return f"the web and {what}"
    if uses == "folder":
        return "the folders you named, no web"
    return "nothing outside its folder"


def own_job(store: Store, job_id: str, owner: str) -> dict | None:
    """The job when it belongs to this owner; another's (or none) -> None."""
    row = jobs.get(store, job_id)
    if row is None or (row["personality"] or "") != owner:
        return None
    return row


def make_worker_tools(store: Store) -> list[FunctionTool]:
    async def start_job(title: str, brief: str, read_dirs: list[str] | None = None,
                        tool_context: ToolContext = None) -> dict:
        """Hand a long job to a background Worker and answer the user now. A job is: code to write and run, a test to run, a check that takes more than one shell command, anything that would take you over a minute, and always trying, cloning, installing, building or running someone else's code or repo (the Worker does it in its sandbox, never in your own shell). One read or one command: do it here yourself; a question (today's market, a sum, a note, a picture): answer here. If unsure, start the job. The Worker runs alone with its own folder, the shell, the web (it clones repos itself) and, when the user asks about them, their mail, calendar or an app; it never asks the user anything (a step that would need their tap is skipped and named in its report) and posts its report into this chat. read_dirs: only folders the user asked the Worker to read (whole paths as they wrote them, at most 3, read-only, no hidden files or git history); a folder they want the result put in is not one: they get a "Keep it" button for it. title: a few words the user will recognise. brief: everything the Worker needs: the goal, where things are, what done looks like, what to leave alone. Tell the user it started and that the result will come here."""
        session_id = chat_of(tool_context)
        if session_id is None:
            return {"error": ONLY_IN_CHAT}
        if len(brief) > BRIEF_MOST:
            return {"error": f"Not started: a brief may be at most {BRIEF_MOST:,} characters. Say it shorter, or put "
                             "the long part in a file the Worker reads."}
        sites = private_sites(store, session_id)
        if sites:
            return {"error": PRIVATE.format(sites=", ".join(sorted(sites)))}
        # The title is the model's even in a chat that read outside text: at most 80 characters of it may ride along.
        # That is the accepted leak bound (simpler Workers, 19 Nov 2026); the brief itself is his own words then.
        clean_title = title.strip()[:80]
        if not clean_title:
            clean_title = "Job"
        from odie.agent import turn
        folders = []
        for given in (read_dirs or [])[:READ_DIRS_MOST]:
            folder, why = readable_dir(str(given), turn.USER_TEXT.get())
            if folder is None:
                return {"error": f"Not started: {why}."}
            folders.append(folder)
        taint = taint_of(store, tool_context)
        typed = typed_words(store, session_id)
        job_brief = brief_for(brief.strip(), typed, taint)
        if job_brief is None:
            return {"error": "Not started: this chat has read outside text, so a job gets only the user's own words "
                             "as its brief, and there are none here to hand over. Ask them to say what they want."}
        from odie.plugins import access
        uses = uses_for(turn.USER_TEXT.get(), list(access.known_tools(store)))
        keep_to = keep_place(typed)
        try:
            job = router.start(clean_title, job_brief, session_id, personality=owner_of(store, tool_context),
                               taint=taint, read_dirs=folders, uses=uses, keep_to=keep_to)
        except router.TooMany as e:
            return {"error": f"Not started: {e}"}
        out = {"job_id": job.id, "status": "started", "folder": str(job.folder), "uses": uses_words(uses)}
        if folders:
            out["may_read"] = folders
        if keep_to:
            out["keep_to"] = keep_to
        if taint:
            out["note"] = (f"This chat read {taint}, so the Worker's brief is the user's own words only (their last "
                           "messages here), not yours.")
        return out

    async def jobs_status(tool_context: ToolContext = None) -> dict:
        """The background jobs: what is running or waiting for a slot, and the last few that ended, with their reports."""
        owner = owner_of(store, tool_context)
        mine = jobs.of_owner(store, owner, 10)
        going = [job_line(j) for j in mine if j["status"] in jobs.GOING]
        ended = []
        for j in mine:
            if j["status"] in jobs.GOING:
                continue
            said = j.get("report") or j.get("error") or ""
            ended.append(f"{job_line(j)}: {said[:200]}")
        return {"running": going, "recent": ended[:5]}

    async def stop_job(job_id: str, tool_context: ToolContext = None) -> dict:
        """Stop a background job by its id (job-…): the user asked, or the job is no longer wanted."""
        if chat_of(tool_context) is None or own_job(store, job_id, owner_of(store, tool_context)) is None:
            return {"error": f"{job_id} can't be stopped here."}
        if not router.stop(job_id):
            return {"error": f"{job_id} isn't running."}
        return {"stopped": job_id}

    async def retry_job(job_id: str, tool_context: ToolContext = None) -> dict:
        """Start a job that ended (failed, stopped, stuck) again by its id, with the same brief and folder: when the user says retry. A step it needed the user's OK for stays refused: only their tap on Pulse ("Allow it and run again") lets it run."""
        if chat_of(tool_context) is None or own_job(store, job_id, owner_of(store, tool_context)) is None:
            return {"error": f"{job_id} can't be retried here."}
        job = router.retry(job_id)
        if job is None:
            return {"error": f"{job_id} can't be retried: it is still going, or it is Odie's own test of a pull request."}
        return {"job_id": job.id, "status": "started again"}

    async def forget_job(job_id: str, tool_context: ToolContext = None) -> dict:
        """Take a failed or stuck job's card off Pulse, when the user dismisses it or says to forget the job."""
        if chat_of(tool_context) is None or own_job(store, job_id, owner_of(store, tool_context)) is None:
            return {"error": f"There's no job {job_id} here."}
        jobs.clear(store, job_id)
        return {"forgotten": job_id}

    return [FunctionTool(start_job), FunctionTool(jobs_status), FunctionTool(stop_job), FunctionTool(retry_job),
            FunctionTool(forget_job)]
