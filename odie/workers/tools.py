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
    job is then tainted (no web, no apps; its shell has no network anyway). odie.workers.taint keeps it for the chat.
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


def readable_dir(given: str, words: str | None) -> tuple[str | None, str]:
    """A folder of his a job may read, checked by code: (its real path, "") or (None, why not). It must be a folder
    under the home (not the home itself), with no hidden part and not in Library (in any case), apart from Odie's own
    folders (not inside them, not around them), and named by the user as a whole path in this turn's own words.
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
    home = true_path(Path.home())
    if not same_or_inside(folder, home) or len(folder.parts) == len(home.parts):
        return None, f"{given}: not a folder under your home"
    parts = folder.parts[len(home.parts):]
    if any(part.startswith(".") for part in parts) or parts[0].casefold() == "library":
        return None, f"{given}: hidden or app data, never readable by a job"
    if any(overlaps(folder, true_path(place)) for place in odie_places()):
        return None, f"{given}: Odie's own folders, never readable by a job"
    if not named_by_user(given, folder, words):
        return None, f"{given}: you didn't name it in your request"
    return str(folder), ""


MAIL_WORDS = re.compile(r"\b(e-?mails?|mail|inbox|gmail|outlook)\b", re.I)
CALENDAR_WORDS = re.compile(r"\b(calendar|meetings?|appointments?)\b", re.I)


def uses_for(words: str | None, read_dirs: list, taint: str, app_names: list[str]) -> str:
    """What a job may reach besides its own folder: ONE of the web, his apps, his named folders, decided by code from
    what the request needs (third review, 19 Nov 2026), so nothing a page says can make it read his mail and send it on.
      the chat read outside text (taint)                     -> "none" (no web, no apps)
      he named a folder                                      -> "folder" (no web, no apps)
      "check my mail for the invoice", "my inbox"            -> "apps:mail" (his apps, no web)
      "list my meetings", "my calendar"                      -> "apps:calendar"
      a connected app named as a word ("use notion to …")    -> "apps"
      anything else ("research e-bikes")                     -> "web" (the web, no apps)"""
    if taint:
        return "none"
    if read_dirs:
        return "folder"
    text = words or ""
    if MAIL_WORDS.search(text):
        return "apps:mail"
    if CALENDAR_WORDS.search(text):
        return "apps:calendar"
    for name in app_names:
        if name and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I):
            return "apps"
    return "web"


def uses_words(uses: str) -> str:
    """What a job uses, as its card says it: "web" -> "the web"; "apps:mail" -> "your mail, no web"; "apps" -> "your
    apps, no web"; "folder" -> "the folders you named, no web"; "none" -> "nothing outside its folder"."""
    if uses == "web":
        return "the web"
    if uses.startswith("apps"):
        what = {"apps:mail": "your mail", "apps:calendar": "your calendar"}.get(uses, "your apps")
        return f"{what}, no web"
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
        """Hand a long job to a background Worker and answer the user now. A job is: code to write and run, a test to run, a check that takes more than one shell command, or anything that would take you over a minute. One read or one command: do it here yourself; a question (today's market, a sum, a note, a picture): answer here. If unsure, start the job. The Worker runs alone with the shell, its own folder, the web and your apps, never asks the user anything (a step that would need their tap is skipped and named in its report), and posts its report into this chat when done or stuck. It can't read the user's files unless they named the folder in this request: then pass it in read_dirs (its whole path, as they wrote it, at most 3), read as plain files (no hidden files, no git history). A job gets ONE of: the web, the user's apps (when they ask about their mail, calendar or an app by name), or named folders; code decides from their words. title: a few words the user will recognise. brief: everything the Worker needs, in full: the goal, where things are, what done looks like, what to leave alone. Tell the user it started and that the result will come here."""
        session_id = chat_of(tool_context)
        if session_id is None:
            return {"error": ONLY_IN_CHAT}
        if len(brief) > BRIEF_MOST:
            return {"error": f"Not started: a brief may be at most {BRIEF_MOST:,} characters. Say it shorter, or put "
                             "the long part in a file the Worker reads."}
        sites = private_sites(store, session_id)
        if sites:
            return {"error": PRIVATE.format(sites=", ".join(sorted(sites)))}
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
        from odie.plugins import access
        uses = uses_for(turn.USER_TEXT.get(), folders, taint, list(access.known_tools(store)))
        try:
            job = router.start(clean_title, brief.strip(), session_id, personality=owner_of(store, tool_context),
                               taint=taint, read_dirs=folders, uses=uses)
        except router.TooMany as e:
            return {"error": f"Not started: {e}"}
        out = {"job_id": job.id, "status": "started", "folder": str(job.folder), "uses": uses_words(uses)}
        if folders:
            out["may_read"] = folders
        if taint:
            out["note"] = f"This chat read {taint} this turn, so the job runs without web, apps or network."
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
