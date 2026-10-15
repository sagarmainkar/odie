"""Replays as chat threads (2026-10-11): each test chat that scripts/chat_replay.sh ran on a throwaway home is copied
into Odie's own folder as a thread, so the owner can open it from Chat → Threads like any of his chats.

Only the conversation is copied: the session and its events (in order, ids and times kept), a thread row with a title,
and the files its replies made (podcasts, screenshots, PDFs). Never the replay's tasks, reminders, memories, trackers
or settings, even though the replay made some (turn 13 adds a reminder and a task, turn 15 a memory).

Which run a throwaway home holds is worked out from what it said, not from when it ran: its replies are compared with
the saved results in evals/chats/*.json, and the one whose replies match names the thread ("Replay · Sonnet 5.5 · think
longer"). A home whose replies match no saved run (a trial run of a turn or two) is left alone.

Each thread gets a session id in the live format, chat-<the run's date>-<n>, numbered from 101 (FIRST_SEGMENT): the
day's own chat uses chat-<date>, -2, -3 and so on after each "new chat", and the app's day view walks those numbers until
one is missing, so it never reaches 101 and the replays stay out of the day's chat.

Safety, because the target is normally the live ~/.odie:
  - it refuses while the target's server answers on its port ("run odie stop first");
  - before writing, it backs up assistant.db and sessions.db (SQLite's own backup) into a folder beside the home,
    ~/.odie-backups/before-replay-threads-<time>/, and prints how to put them back;
  - a replay already imported (its title or its first event is there) is skipped, so running it twice adds nothing;
  - --dry-run prints the plan and writes nothing.

    scripts/replay_to_threads.sh --all --dry-run          what it would import from every throwaway home
    scripts/replay_to_threads.sh --all                    import them (Odie stopped first)
    scripts/replay_to_threads.sh <throwaway home>         just one (…/odie-chat-replay-xxxx/home)
    scripts/replay_to_threads.sh --all --from <folder>    look for throwaway homes there instead of the temp folder"""
from __future__ import annotations

import json
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from odie import blocks_eval as be
from odie import chat_replay as cr

EVALS_DIR = be.REPO / "evals" / "chats"
HOME_GLOB = "odie-chat-replay-*/home"  # where chat_replay.py makes its throwaway homes, inside the temp folder
FIRST_SEGMENT = 101  # imported threads are chat-<date>-101, -102, …: far past any "new chat" the owner makes in a day
BACKUPS_FOLDER = ".odie-backups"  # beside Odie's home: ~/.odie → ~/.odie-backups
MEDIA_ID = re.compile(r"[0-9a-f]{16}")  # odie.media ids; only ones with a saved file in the replay's media folder count
UPLOAD_MARK = re.compile(r"\[image:([0-9a-f]{6,64})\]")  # a picture the user sent (odie.app.runner.IMAGE_MARK)

# The names the owner calls the models by, for thread titles. A model not listed keeps its own id.
MODEL_NAMES = {
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-opus-5-5": "Opus 5.5",
    "gemma-4-26b-a4b-it-qat": "Gemma 4 26B",
    "qwen3.8-27b-splash": "Qwen 3.8 27B splash",
    "glm-5.3-flash:cloud": "GLM 5.3 Flash",
}


@dataclass
class Replay:
    """One replay found in a throwaway home, and what it would become in the target."""
    home: Path              # …/odie-chat-replay-xxxx/home
    session_id: str         # its session there: "replay-2026-10-11"
    turns: int              # the user's messages in it
    events: int
    first_event: str        # the id of its first event: the same id in the target means it was imported already
    results: Path | None = None  # the evals/chats file whose replies match, or None
    matched: int = 0        # how many of that file's replies are the same
    title: str = ""
    date: str = ""
    skip: str = ""          # why it won't be imported ("" = it will)
    new_id: str = ""        # the thread's session id in the target, once planned


# ── Finding the replays and naming them ─────────────────────────────────────────────────────────────────────────────

def replay_homes(root: Path) -> list[Path]:
    """The throwaway homes chat_replay.py left in `root` (the temp folder): each odie-chat-replay-*/home that has a
    sessions.db, oldest name first."""
    return [h for h in sorted(root.glob(HOME_GLOB)) if (h / "data" / "sessions.db").is_file()]


def replay_session_ids(sessions_db: Path) -> list[str]:
    """The replay sessions in a throwaway home's database (read only): ids starting "replay-"."""
    with cr.read_only(sessions_db) as conn:
        rows = conn.execute("select id from sessions where id like 'replay-%' order by create_time").fetchall()
    return [r[0] for r in rows]


def same_replies(turns: list[dict], results: dict) -> int:
    """How many turns gave exactly the reply a saved run recorded, turn by turn (spaces at either end ignored).
      replies ["Hi", "A table"] vs saved ["Hi", "A list"] → 1"""
    count = 0
    for mine, saved in zip(turns, results.get("turns") or []):
        if mine["reply"].strip() == (saved.get("reply") or "").strip():
            count += 1
    return count


def is_sure_match(best: int, runner_up: int, turns: int) -> bool:
    """Whether the best-matching saved run is surely this replay: at least half its replies are the same, and no other
    run matches even half. Replies differ from run to run (and model to model), so a real match stands out.
      17 turns, best 15, runner-up 0 → True (Gemma after fixes: two replies differ in their spacing)
      17 turns, best 3, runner-up 0  → False (too few: a different run of the same model)
      1 turn (a trial run), best 0   → False"""
    half = turns / 2
    return turns > 0 and best >= half and runner_up < half


def display_name(model: str) -> str:
    """"claude-sonnet-5-5" → "Sonnet 5.5"; a model not in MODEL_NAMES → its own id."""
    return MODEL_NAMES.get(model, model)


def thread_title(results: dict, stem: str) -> str:
    """The thread's title, from a saved run: the model, "think longer" when it was on, and whatever the file's name adds
    after the model (e.g. "after fixes").
      opus, thinking on, "2026-10-11-anthropic-claude-opus-5-5-think-longer" → "Replay · Opus 5.5 · think longer"
      gemma, thinking off, "2026-10-11-lmstudio-gemma-4-26b-a4b-it-qat-after-fixes" → "Replay · Gemma 4 26B · after fixes"
      sonnet, thinking off, "2026-10-11-anthropic-claude-sonnet-5-5" → "Replay · Sonnet 5.5" """
    pieces = [display_name(results["model"])]
    if (results.get("settings") or {}).get("thinking"):
        pieces.append("think longer")
    usual_stem = be.file_stem(results["date"], results["provider"], results["model"])
    extra = stem.removeprefix(usual_stem).replace("-think-longer", "").strip("-")
    if extra:
        pieces.append(extra.replace("-", " "))
    return "Replay · " + " · ".join(pieces)


def saved_runs(evals_dir: Path) -> dict[Path, dict]:
    """The saved replays in evals/chats (source "replay"), by file. Live chats imported there are not replays."""
    runs = {}
    for path in cr.saved_chats(evals_dir):
        results = json.loads(path.read_text())
        if results.get("source") == "replay":
            runs[path] = results
    return runs


def describe(home: Path, session_id: str, runs: dict[Path, dict]) -> Replay:
    """One replay in a throwaway home: its size, and the saved run it matches (or why it has none)."""
    db = home / "data" / "sessions.db"
    turns = cr.import_session(db, session_id)
    with cr.read_only(db) as conn:
        events = conn.execute("select count(*) from events where session_id=?", (session_id,)).fetchone()[0]
        first = conn.execute("select id from events where session_id=? order by timestamp limit 1", (session_id,)).fetchone()
    replay = Replay(home=home, session_id=session_id, turns=len(turns), events=events, first_event=first[0] if first else "")
    scores = sorted(((same_replies(turns, results), path) for path, results in runs.items()), reverse=True)
    best, best_path = scores[0] if scores else (0, None)
    runner_up = scores[1][0] if len(scores) > 1 else 0
    if best_path is None or not is_sure_match(best, runner_up, len(runs[best_path]["turns"])):
        replay.skip = f"no saved run matches it (user turns: {len(turns)})"
        return replay
    results = runs[best_path]
    replay.results = best_path
    replay.matched = best
    replay.title = thread_title(results, best_path.stem)
    replay.date = results["date"]
    return replay


def find_replays(homes: list[Path], evals_dir: Path) -> list[Replay]:
    """Every replay in these throwaway homes, matched to its saved run. Two homes matching the same run: the second
    is skipped (it would be the same thread twice)."""
    runs = saved_runs(evals_dir)
    found: list[Replay] = []
    for home in homes:
        for session_id in replay_session_ids(home / "data" / "sessions.db"):
            found.append(describe(home, session_id, runs))
    taken: dict[Path, Replay] = {}
    for replay in found:
        if replay.skip:
            continue
        if replay.results in taken:
            replay.skip = f"same run as {taken[replay.results].home.parent.name}"
            continue
        taken[replay.results] = replay
    return found


# ── Safety ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def server_answers(host: str, port: int) -> bool:
    """Whether something answers on Odie's port, i.e. the server is running and may write the databases meanwhile.
    A server listening on every address ("0.0.0.0") is asked on this computer's own address.
      Odie running on 8000 → True;  stopped → False"""
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def backup_folder(home: Path, now: datetime) -> Path:
    """Where the backups go: a folder beside Odie's home, never inside it.
      /Users/me/.odie at 2026-10-11 21:40:05 → /Users/me/.odie-backups/before-replay-threads-2026-10-11-214005"""
    return home.parent / BACKUPS_FOLDER / f"before-replay-threads-{now.strftime('%Y-%m-%d-%H%M%S')}"


def backup_databases(data_dir: Path, folder: Path) -> list[Path]:
    """Copies assistant.db and sessions.db with SQLite's own backup (which includes anything still in the -wal file),
    so a plain file copy of a half-written database is never what's kept. Returns the copies."""
    folder.mkdir(parents=True, exist_ok=True)
    copies = []
    for name in ("assistant.db", "sessions.db"):
        source = sqlite3.connect(data_dir / name)
        copy = sqlite3.connect(folder / name)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        copies.append(folder / name)
    return copies


# ── Copying one replay ─────────────────────────────────────────────────────────────────────────────────────────────

def free_session_id(conn: sqlite3.Connection, date: str, taken: set[str]) -> str:
    """The first chat-<date>-<n> from FIRST_SEGMENT up that no session in the target uses (nor one planned already).
      none imported yet → "chat-2026-10-11-101";  101 there → "chat-2026-10-11-102" """
    n = FIRST_SEGMENT
    while True:
        session_id = f"chat-{date}-{n}"
        used = conn.execute("select 1 from sessions where id=?", (session_id,)).fetchone()
        if not used and session_id not in taken:
            return session_id
        n += 1


def already_there(sessions: sqlite3.Connection, assistant: sqlite3.Connection, replay: Replay) -> str:
    """Why this replay is already in the target, or "" when it isn't: a thread with its title, or its first event in
    some session (an earlier import, even one renamed since).
      "Replay · Opus 5.5" in threads → 'a thread is already called "Replay · Opus 5.5"';  nothing there → "" """
    titled = assistant.execute("select session_id from threads where title=?", (replay.title,)).fetchone()
    if titled:
        return f'a thread is already called "{replay.title}" ({titled[0]})'
    copied = sessions.execute("select session_id from events where id=?", (replay.first_event,)).fetchone()
    if copied:
        return f"already imported as {copied[0]}"
    return ""


def files_made(replay: Replay) -> tuple[list[str], list[str]]:
    """The media ids and the uploaded pictures this replay's events name, that the throwaway home has files for:
    media is what tools made (a podcast, a screenshot, a PDF); uploads are pictures the user sent. A media item's
    description can name more media (a deck's slide previews), so those count too.
      a speak result {"media": {"id": "73ac143af5d147a7", …}} with media/73ac143af5d147a7.json there → (["73ac…"], [])"""
    db = replay.home / "data" / "sessions.db"
    with cr.read_only(db) as conn:
        texts = [r[0] for r in conn.execute("select event_data from events where session_id=?", (replay.session_id,))]
    media_dir = replay.home / "data" / "media"
    media: list[str] = []
    waiting = [m for text in texts for m in MEDIA_ID.findall(text)]
    while waiting:
        mid = waiting.pop(0)
        sidecar = media_dir / f"{mid}.json"
        if mid in media or not sidecar.is_file():
            continue
        media.append(mid)
        waiting += MEDIA_ID.findall(sidecar.read_text())
    uploads_dir = replay.home / "data" / "uploads"
    uploads = []
    for text in texts:
        for iid in UPLOAD_MARK.findall(text):
            if iid not in uploads and (uploads_dir / f"{iid}.jpg").is_file():
                uploads.append(iid)
    return media, uploads


def copy_files(replay: Replay, media: list[str], uploads: list[str], target_data: Path) -> int:
    """Copies the media (each id's file and its .json description) and uploaded pictures into the target, keeping
    their ids. A file the target already has is left as it is. Returns how many files were copied."""
    copied = 0
    pairs = []
    for mid in media:
        for path in sorted((replay.home / "data" / "media").glob(f"{mid}.*")):
            pairs.append((path, target_data / "media" / path.name))
    for iid in uploads:
        pairs.append((replay.home / "data" / "uploads" / f"{iid}.jpg", target_data / "uploads" / f"{iid}.jpg"))
    for source, target in pairs:
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def copy_session(replay: Replay, target: sqlite3.Connection, app_name: str, user_id: str) -> None:
    """Copies the replay's session row and every event into the target's sessions database under the new id and
    the target's own app and user names, in one transaction: all of it lands, or none of it."""
    with cr.read_only(replay.home / "data" / "sessions.db") as source:
        state, created, updated = source.execute("select state, create_time, update_time from sessions where id=?",
                                                 (replay.session_id,)).fetchone()
        events = source.execute("select id, invocation_id, timestamp, event_data from events where session_id=? "
                                "order by timestamp", (replay.session_id,)).fetchall()
    with target:
        target.execute("insert into sessions(app_name, user_id, id, state, create_time, update_time) values (?,?,?,?,?,?)",
                       (app_name, user_id, replay.new_id, state, created, updated))
        for event_id, invocation_id, timestamp, data in events:
            target.execute("insert into events(id, app_name, user_id, session_id, invocation_id, timestamp, event_data) "
                           "values (?,?,?,?,?,?,?)", (event_id, app_name, user_id, replay.new_id, invocation_id, timestamp, data))


# ── The plan and the import ────────────────────────────────────────────────────────────────────────────────────────

def plan(replays: list[Replay], data_dir: Path) -> list[Replay]:
    """Gives each replay still to import its new session id, and skips the ones the target already has. Read only.
    Returns the ones to import."""
    sessions = cr.read_only(data_dir / "sessions.db")
    assistant = cr.read_only(data_dir / "assistant.db")
    todo: list[Replay] = []
    taken: set[str] = set()
    try:
        for replay in replays:
            if replay.skip:
                continue
            replay.skip = already_there(sessions, assistant, replay)
            if replay.skip:
                continue
            replay.new_id = free_session_id(sessions, replay.date, taken)
            taken.add(replay.new_id)
            todo.append(replay)
    finally:
        sessions.close()
        assistant.close()
    return todo


def import_all(todo: list[Replay], data_dir: Path, app_name: str, user_id: str) -> None:
    """Imports the planned replays: files first, then the session and its events, then the thread's title (the app
    lists a thread once its events are there; the title row only names it)."""
    from odie import threads
    from odie.store.db import Store
    sessions = sqlite3.connect(data_dir / "sessions.db")
    store = Store(data_dir / "assistant.db")
    try:
        for replay in todo:
            media, uploads = files_made(replay)
            copied = copy_files(replay, media, uploads, data_dir)
            copy_session(replay, sessions, app_name, user_id)
            threads.rename(store, replay.new_id, replay.title)
            print(f"  ✓ {replay.title} → {replay.new_id} ({replay.events} events, {copied} files copied)")
    finally:
        sessions.close()
        store.close()


def print_plan(replays: list[Replay], where: Path) -> None:
    print(f"Replays in {where}:")
    if not replays:
        print("  none found")
    for replay in replays:
        name = replay.home.parent.name
        if replay.results is None:
            print(f"  {name}: skipped, {replay.skip}")
            continue
        media, uploads = files_made(replay)
        print(f"  {name} = {replay.results.name} ({replay.matched} of {replay.turns} replies the same)")
        if replay.skip:
            print(f"      skipped: {replay.skip}")
        else:
            print(f'      → "{replay.title}" as {replay.new_id}: {replay.turns} user turns, {replay.events} events, '
                  f"{len(media)} media, {len(uploads)} pictures")


def restore_commands(folder: Path, data_dir: Path) -> list[str]:
    """How to undo the import with the backup (Odie stopped): SQLite's .restore puts each database back whole."""
    return [f'sqlite3 "{data_dir / name}" ".restore \'{folder / name}\'"' for name in ("assistant.db", "sessions.db")]


def main(argv: list[str]) -> int:
    from odie import config
    s = config.settings
    dry_run = "--dry-run" in argv
    data_dir = s.data_dir
    home = s.home or data_dir.parent

    # Step 1: the throwaway homes to read.
    if "--all" in argv:
        where = Path(cr.option(argv, "--from") or tempfile.gettempdir())
        homes = replay_homes(where)
    else:
        given = [a for a in argv if not a.startswith("--")]
        if len(given) != 1:
            print("usage: scripts/replay_to_threads.sh --all [--from <folder>] [--dry-run]\n"
                  "       scripts/replay_to_threads.sh <throwaway home> [--dry-run]")
            return 2
        where = Path(given[0]).expanduser()
        homes = [where]
    print(f"Target: {home} (data {data_dir}, chats stored as {s.app_name}/{s.user_id})")
    if not (data_dir / "sessions.db").is_file() or not (data_dir / "assistant.db").is_file():
        print(f"No Odie databases in {data_dir}: start Odie there once first.")
        return 1

    # Step 2: match each replay to its saved run, and plan its thread.
    replays = find_replays(homes, EVALS_DIR)
    todo = plan(replays, data_dir)
    print_plan(replays, where)
    running = server_answers(s.host, s.port)
    if dry_run:
        print(f"Dry run: nothing written. {len(todo)} to import." + (f" Odie is running on port {s.port}: run odie stop first." if running else ""))
        return 0
    if not todo:
        print("Nothing to import.")
        return 0
    if running:
        print(f"Odie is running on port {s.port}: run odie stop first (it may write the databases meanwhile). Nothing written.")
        return 1

    # Step 3: back up both databases, then import.
    folder = backup_folder(home, datetime.now())
    backup_databases(data_dir, folder)
    print(f"Backed up assistant.db and sessions.db to {folder}")
    import_all(todo, data_dir, s.app_name, s.user_id)
    print(f"Imported {len(todo)}. To undo (Odie stopped):")
    for line in restore_commands(folder, data_dir):
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
