"""Everything Odie makes in the background (explainer videos, podcasts, decks, research) is made one at a time,
after the chat turn that asked for it has ended. A finished one is posted into that chat with a phone push, the way
reminders are; a failed one says why in one line; a job that a restart cut off is told once.

Each kind registers itself in KINDS with two steps: writing (the only model call: a focused turn, see
odie.making.writer) and making (no AI: render a video, speak a podcast, build a deck, save a report). The queue runs
a job's steps and tells the chat "The {word} about {title} is ready." (a kind may add to that line: research adds its
short answer), or that it didn't finish, or was interrupted.

Each job has a folder, <data>/workspace/<the kind's folder>/<slug>/, holding what its steps make, job.json (status:
queued, writing, making, done, failed or interrupted_told; a video's job.json from before the queue was shared may say
"running", which meant making) and brief.md. A job starts as a topic, a length and a brief (the chat model's brief and
any sources, word for word: odie.making.sources); the writing step first writes the brief to brief.md, kept
for later, then turns them into the title and the kind's own results (job.data). job.json never holds the brief."""
from __future__ import annotations

import asyncio
import contextvars
import importlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from odie import persona
from odie.agent.tools.files import workspace
from odie.browser import render_browser
from odie.making.writer import WriterFailed
from odie.push.send import send_to_all

log = logging.getLogger("odie.making")

# runner (posts the messages, runs the writer's focused turn) and store (the push needs it); set by the runner
hooks: dict = {}
LINE_LIMIT = 200  # characters of an error kept in the chat
UNKNOWN_ERROR = "something went wrong (see Odie's log)"
# The queue lives in memory, so after a restart a job that was waiting, writing or making was "cut off". "running" is
# what a video's job.json said for making before the queue was shared.
INTERRUPTED_STATUSES = ("queued", "writing", "making", "running")
# The modules of Odie's own kinds: each puts its Kind in KINDS when imported (load_kinds).
BUILT_IN_KINDS = ("odie.video.kind", "odie.making.podcast", "odie.making.deck", "odie.making.research",
                  "odie.making.story")


@dataclass
class Job:
    """One thing to make. kind names its entry in KINDS; data holds what the writing step produced for the making
    step (a video's narration and page body), and is never written to job.json."""
    slug: str
    title: str
    session_id: str | None
    folder: Path
    kind: str = "video"
    voice_name: str = ""
    topic: str = ""
    minutes: int = 2
    brief: str = ""
    data: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)


def always_needs_writing(job: Job) -> bool:
    """Kind.needs_writing for kinds whose jobs always start unwritten: any job -> True."""
    return True


@dataclass
class Kind:
    """One kind of thing Odie makes.
    word: how the chat names it: "video" -> "The video about X is ready."
    folder: where its jobs live in the workspace, a folder of its own: "videos" -> <workspace>/videos/<slug>/.
    write(job, turn, browser): the writing step; fills in job.title and job.data. turn is runner.focused_turn.
    make(job, browser, transport): the making step; makes the file and returns its hand_over media, which the "is
    ready" message carries.
    known_errors: the error types whose words are written for the user, so a failure shows them (VoiceUnavailable:
    "Odie's local voice isn't running"); anything else is said as "something went wrong".
    needs_writing(job): whether the job still has to be written; by default every job does.
    ready_text(job): what the chat is told when the job is ready, starting with ready_line; None (the default) says
    ready_line alone: "The video about Tides is ready." Research adds its short answer below it."""
    word: str
    folder: str
    write: Callable[[Job, Callable, object], Awaitable[None]]
    make: Callable[[Job, object, object], Awaitable[dict]]
    known_errors: tuple[type[Exception], ...] = ()
    needs_writing: Callable[[Job], bool] = always_needs_writing
    ready_text: Callable[[Job], str] | None = None


# Every kind by its name ("video"). A kind registers by putting itself here when its module is imported.
KINDS: dict[str, Kind] = {}


def load_kinds() -> None:
    """Import Odie's own kinds, so each is in KINDS (importing one twice does nothing)."""
    for name in BUILT_IN_KINDS:
        importlib.import_module(name)


# The line: jobs wait in _queue, one worker takes them in turn, _waiting counts the ones waiting plus the one running.
_queue: asyncio.Queue | None = None
_worker: asyncio.Task | None = None
_waiting = 0


def queue_position() -> int:
    """How many jobs (of any kind) are waiting or being made: nothing going on -> 0; one being made and one behind it
    -> 2."""
    return _waiting


def submit(job: Job) -> int:
    """Put a job in line (starting the worker on the first one) and say its place: with nothing else going on -> 1
    (it is made now); with one already being made -> 2 (it is next). Needs the running event loop."""
    global _queue, _worker, _waiting
    if _worker is None or _worker.done():
        _queue = asyncio.Queue()
        # The worker starts in a fresh, empty context, not a copy of this chat turn's: a task copies the context it
        # was created in, and the worker outlives the turn and runs every later job. Example: a private chat (it read
        # amazon.in) queues a deck first; a podcast queued later from a public chat must not see that chat's words or
        # its private sites. A job that needs the asking chat's private sites carries them itself (the deck's).
        _worker = asyncio.create_task(work(_queue), context=contextvars.Context())
    write_job(job, "queued")
    _waiting += 1
    _queue.put_nowait(job)
    return _waiting


async def work(queue: asyncio.Queue) -> None:
    """Take jobs one at a time, forever. A job that fails is logged and the next one still runs."""
    global _waiting
    while True:
        job = await queue.get()
        try:
            await run(job)
        except Exception:  # noqa: BLE001 (run() says its own failures in the chat; this is for what it couldn't)
            log.exception("%s job %s broke", job.kind, job.slug)
        finally:
            _waiting -= 1
            queue.task_done()


def job_file(folder: Path) -> Path:
    return folder / "job.json"


def save_json(folder: Path, data: dict) -> None:
    """Write job.json whole or not at all: a temporary file first, then a rename over the real one."""
    target = job_file(folder)
    temporary = folder / "job.json.tmp"
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(target)


def write_brief(job: Job) -> None:
    """Keep the writer's brief in the job's folder as brief.md, as the writer reads it (with a closing newline)."""
    job.folder.mkdir(parents=True, exist_ok=True)
    (job.folder / "brief.md").write_text(job.brief + "\n", encoding="utf-8")


def write_job(job: Job, status: str, error: str = "") -> None:
    data = {"status": status, "kind": job.kind, "title": job.title, "session_id": job.session_id, "slug": job.slug,
            "created": job.created, "topic": job.topic, "minutes": job.minutes}
    if error:
        data["error"] = error
    job.folder.mkdir(parents=True, exist_ok=True)
    save_json(job.folder, data)


def one_line(error: Exception, known: tuple[type[Exception], ...]) -> str:
    """What the chat is told about a failure, in one line of at most 200 characters. The writer's own failures and the
    kind's known errors (`known`: words written for the user, like the voice that isn't running, ffmpeg's complaint,
    the browser's) keep their first line, without a closing full stop: VoiceUnavailable("Odie's local voice isn't
    running.") with VoiceUnavailable known -> "Odie's local voice isn't running". Anything else is not shown, because
    it may hold paths or internals: KeyError("/some/path") -> "something went wrong (see Odie's log)"."""
    shown = (WriterFailed, *known)
    if not isinstance(error, shown):
        return UNKNOWN_ERROR
    lines = str(error).strip().splitlines()
    first = lines[0] if lines else ""
    return first[:LINE_LIMIT].rstrip(".")


def push_tag(kind_name: str, slug: str) -> str:
    """The push's tag, one per job, so a later push about the same job replaces it: "video", "attention" ->
    "video-attention"."""
    return f"{kind_name}-{slug}"


async def tell(tag: str, session_id: str | None, text: str, media: list[dict] | None = None) -> None:
    """Post the message into the chat and push it to the phone (one push per message, with the job's tag)."""
    await hooks["runner"].post_message(text, session_id, media=media, kind="job")
    store = hooks["store"]
    try:
        send_to_all(store, persona.get(store)["name"], text, url="/#chat", tag=tag)
    except Exception:  # noqa: BLE001 (a failed push never loses the post)
        log.warning("push failed for %s", tag, exc_info=True)


def ready_line(word: str, title: str) -> str:
    """The first line of every "is ready" message: "video", "Tides" -> "The video about Tides is ready."."""
    return f"The {word} about {title} is ready."


def ready_message(kind: Kind, job: Job) -> str:
    """What the chat is told when a job is ready: the kind's own ready_text when it has one, else ready_line alone. A
    video about Tides -> "The video about Tides is ready."; research -> that line, a blank line, its short answer."""
    if kind.ready_text is None:
        return ready_line(kind.word, job.title)
    return kind.ready_text(job)


def title_after_writing(written_title: str, job: Job) -> str:
    """The title the finished thing goes by: the writer's own, trimmed ("  How attention works " -> "How attention
    works"); with none, the job's topic ("" and topic "attention" -> "attention"); with neither, the title the job
    already had."""
    title = written_title.strip()
    if title:
        return title
    if job.topic:
        return job.topic
    return job.title


async def run(job: Job, browser=None, transport=None, turn=None) -> None:
    """Make one job and tell its chat: ready (with the file under the message) or didn't finish (and why). A job that
    needs writing is written first (status "writing"; `turn` is the focused model turn, the runner's by default), then
    made (status "making"). Cancellation (Odie shutting down) is not a failure: it passes through, job.json stays
    "writing" or "making" and nothing is posted, so the next start tells the chat the job was interrupted."""
    kind = KINDS[job.kind]
    try:
        if browser is None:
            browser = render_browser()
        if kind.needs_writing(job):
            write_job(job, "writing")
            write_brief(job)
            if turn is None:
                turn = hooks["runner"].focused_turn
            await kind.write(job, turn, browser)
        write_job(job, "making")
        media = await kind.make(job, browser, transport)
        text = ready_message(kind, job)
    except Exception as error:  # noqa: BLE001 (whatever went wrong is said in the chat, never lost)
        await tell_failure(job, kind, error)
        return

    await tell(push_tag(job.kind, job.slug), job.session_id, text, media=[media])
    write_job(job, "done")


async def tell_failure(job: Job, kind: Kind, error: Exception) -> None:
    """Record the failure in job.json and say it in the chat. A job.json that can't be written (disk full) is logged,
    and the chat is still told."""
    reason = one_line(error, kind.known_errors)
    if reason == UNKNOWN_ERROR:
        log.error("%s %s failed", job.kind, job.slug, exc_info=error)
    try:
        write_job(job, "failed", error=reason)
    except OSError:
        log.warning("%s %s: job.json couldn't be written", job.kind, job.slug, exc_info=True)
    text = f"The {kind.word} about {job.title} didn't finish: {reason}."
    await tell(push_tag(job.kind, job.slug), job.session_id, text)


async def stop() -> None:
    """At shutdown, before the browser closes: end the worker and any step in progress. The running job's job.json
    stays "writing" or "making" and the chat hears nothing now; the next start's recover() tells it, once, as
    interrupted."""
    global _worker
    worker = _worker
    if worker is None:
        return
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass
    _worker = None


async def recover() -> int:
    """At startup: every job file, in every kind's folder, still saying queued, writing or making (or a video's old
    "running") was cut off by the restart. Tell its chat once, naming the kind of the folder it is in, and mark it
    interrupted_told, so the next start stays quiet. Returns how many were told."""
    load_kinds()
    told = 0
    for name, kind in KINDS.items():
        root = workspace() / kind.folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/job.json")):
            if await tell_if_interrupted(path, name, kind):
                told += 1
    return told


async def tell_if_interrupted(path: Path, kind_name: str, kind: Kind) -> bool:
    """Tell one job file's chat that it was interrupted, if it was, and mark it told. Returns whether it was told: a
    file saying "making" -> told, True; "done" -> left alone, False; a file that can't be read, or a chat that can't be
    told now -> False, left as it was (the next start tries again)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("job file %s can't be read; skipped", path)
        return False
    if not is_interrupted(data):
        return False
    slug = data.get("slug") or path.parent.name
    title = data.get("title") or slug
    text = f"The {kind.word} about {title} was interrupted (Odie restarted). Ask me again to make it."
    try:
        await tell(push_tag(kind_name, slug), data.get("session_id"), text)
    except Exception:  # noqa: BLE001 (stays as it was, so the next start tries again)
        log.warning("couldn't tell the chat about interrupted %s %s", kind_name, slug, exc_info=True)
        return False
    data["status"] = "interrupted_told"
    save_json(path.parent, data)
    return True


def is_interrupted(data: dict) -> bool:
    """Was this job cut off by a restart? {"status": "making"}, "writing" or "queued" (the line was in memory) -> yes;
    {"status": "running"} (a video's job.json from before the queue was shared) -> yes; {"status": "done"}, "failed"
    or "interrupted_told" -> no (finished, or already told)."""
    return data.get("status") in INTERRUPTED_STATUSES
