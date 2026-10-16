"""Explainer videos are made one at a time, in the background, after the chat turn that asked for them has ended. A
finished video is posted into that chat with a phone push, the way reminders are; a failed one says why in one line; a
job that a restart cut off is told once. The only model call is the writer's turn (odie.video.writer); the rest is
narrating, drawing and joining.

Each job has a folder, <data>/workspace/videos/<slug>/, holding pages/ (every page the writer submitted: page-1.html,
page-2.html, …), page.html (the accepted page as it was drawn, with its timings), narration.wav, the segment files,
<slug>.mp4 and job.json (status: queued, writing, running, done, failed or interrupted_told). A job starts as a topic,
a length and a brief; its first step is the writer, which turns them into the title, the narration and the page. The
brief is kept only in memory, for the writer: it isn't written to job.json or anywhere else in the folder."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from odie import persona, voice
from odie.agent.tools.files import hand_over, workspace
from odie.browser import render_browser
from odie.browser.engine import BrowserError
from odie.push.send import send_to_all
from odie.video import timeline, writer
from odie.video.encode import EncodeError, mux, probe
from odie.video.narrate import narrate
from odie.video.page import assemble
from odie.video.render import render

log = logging.getLogger("odie.video")

hooks: dict = {}  # runner (posts the messages) and store (the push needs it); set by the runner when it starts
LINE_LIMIT = 200  # characters of an error kept in the chat
UNKNOWN_ERROR = "something went wrong (see Odie's log)"
# The queue lives in memory, so after a restart a job that was waiting, writing or rendering was "cut off".
INTERRUPTED_STATUSES = ("queued", "writing", "running")


@dataclass
class Job:
    slug: str
    title: str
    session_id: str | None
    voice_name: str
    folder: Path
    topic: str = ""
    minutes: int = 2
    brief: str = ""
    narration: list[str] = field(default_factory=list)  # filled by the writing step
    body: str = ""  # filled by the writing step
    created: float = field(default_factory=time.time)


# The line: jobs wait in _queue, one worker takes them in turn, _waiting counts the ones waiting plus the one running.
_queue: asyncio.Queue | None = None
_worker: asyncio.Task | None = None
_waiting = 0


def queue_position() -> int:
    """How many videos are waiting or being made: nothing going on -> 0; one rendering and one behind it -> 2."""
    return _waiting


def submit(job: Job) -> int:
    """Put a job in line (starting the worker on the first one) and say its place: with nothing else going on -> 1
    (it renders now); with one already rendering -> 2 (it is next). Needs the running event loop."""
    global _queue, _worker, _waiting
    if _worker is None or _worker.done():
        _queue = asyncio.Queue()
        _worker = asyncio.create_task(work(_queue))
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
            log.exception("video job %s broke", job.slug)
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


def write_job(job: Job, status: str, error: str = "") -> None:
    data = {"status": status, "title": job.title, "session_id": job.session_id, "slug": job.slug,
            "created": job.created, "topic": job.topic, "minutes": job.minutes}
    if error:
        data["error"] = error
    job.folder.mkdir(parents=True, exist_ok=True)
    save_json(job.folder, data)


def one_line(error: Exception) -> str:
    """What the chat is told about a failure, in one line of at most 200 characters. Errors whose words are written
    for the user (the voice isn't running, ffmpeg's complaint, the browser's complaint, the writer's) keep their first line, without
    a closing full stop: VoiceUnavailable("Odie's local voice isn't running.") -> "Odie's local voice isn't running".
    Anything else is not shown, because it may hold paths or internals: KeyError("/some/path") -> "something went
    wrong (see Odie's log)"."""
    if not isinstance(error, (voice.VoiceUnavailable, EncodeError, BrowserError, writer.WriterFailed)):
        return UNKNOWN_ERROR
    lines = str(error).strip().splitlines()
    first = lines[0] if lines else ""
    return first[:LINE_LIMIT].rstrip(".")


async def tell(slug: str, session_id: str | None, text: str, media: list[dict] | None = None) -> None:
    """Post the message into the chat and push it to the phone (one push per message, tagged for this video)."""
    await hooks["runner"].post_message(text, session_id, media=media)
    store = hooks["store"]
    try:
        send_to_all(store, persona.get(store)["name"], text, url="/#chat", tag=f"video-{slug}")
    except Exception:  # noqa: BLE001 (a failed push never loses the post)
        log.warning("video push failed", exc_info=True)


async def make_video(job: Job, browser, transport) -> Path:
    """The steps from narration to a checked MP4 file; returns the MP4's path. Any step may raise."""
    folder = job.folder
    wav, lengths = await narrate(hooks["store"], job.narration, job.voice_name, transport=transport)

    starts, _total = timeline.scene_starts(lengths, timeline.BREATH)
    timings = {"starts": starts, "lengths": lengths}

    narration_wav = folder / "narration.wav"
    narration_wav.write_bytes(wav)
    (folder / "page.html").write_text(assemble(job.body, timings), encoding="utf-8")

    segments = await render(browser, job.body, timings, folder, timeline.FPS, timeline.TABS)
    mp4 = folder / f"{job.slug}.mp4"
    await mux(segments, narration_wav, mp4)

    info = await probe(mp4)
    if not info["video"] or not info["audio"]:
        raise EncodeError("The finished file is missing its picture or its sound.")
    return mp4


def needs_writing(job: Job) -> bool:
    """Decides whether the writer must make this job's page first: a job with a topic and no page yet -> True; a job
    that already carries its narration and page (made the old way, with the page in hand) -> False, it goes straight
    to drawing."""
    has_page = bool(job.narration) and bool(job.body)
    return not has_page


def title_after_writing(written_title: str, job: Job) -> str:
    """The title the finished video goes by: the writer's own, trimmed ("  How attention works " -> "How attention
    works"); with none, the job's topic ("" and topic "attention" -> "attention"); with neither, the title the job
    already had."""
    title = written_title.strip()
    if title:
        return title
    if job.topic:
        return job.topic
    return job.title


async def run(job: Job, browser=None, transport=None, turn=None) -> None:
    """Make one video and tell its chat: ready (with the video under the message) or didn't finish (and why). A job
    without a page is written first (status "writing"; `turn` is the focused model turn, the runner's by default).
    Cancellation (Odie shutting down) is not a failure: it passes through, job.json stays "writing" or "running" and
    nothing is posted, so the next start tells the chat the video was interrupted."""
    try:
        if browser is None:
            browser = render_browser()
        if needs_writing(job):
            write_job(job, "writing")
            if turn is None:
                turn = hooks["runner"].focused_turn
            written = await writer.write(job.topic, job.minutes, job.brief, job.folder, turn, browser)
            job.title = title_after_writing(written.title, job)
            job.narration = written.narration
            job.body = written.body
        write_job(job, "running")
        mp4 = await make_video(job, browser, transport)
        handed = hand_over(mp4, job.title)
    except Exception as error:  # noqa: BLE001 (whatever went wrong is said in the chat, never lost)
        await tell_failure(job, error)
        return

    await tell(job.slug, job.session_id, f"The video about {job.title} is ready.", media=[handed["media"]])
    write_job(job, "done")


async def tell_failure(job: Job, error: Exception) -> None:
    """Record the failure in job.json and say it in the chat. A job.json that can't be written (disk full) is logged,
    and the chat is still told."""
    reason = one_line(error)
    if reason == UNKNOWN_ERROR:
        log.error("video %s failed", job.slug, exc_info=error)
    try:
        write_job(job, "failed", error=reason)
    except OSError:
        log.warning("video %s: job.json couldn't be written", job.slug, exc_info=True)
    await tell(job.slug, job.session_id, f"The video about {job.title} didn't finish: {reason}.")


async def stop() -> None:
    """At shutdown, before the browser closes: end the worker and any render in progress. The running job's job.json
    stays "running" and the chat hears nothing now; the next start's recover() tells it, once, as interrupted."""
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
    """At startup: every job file still saying queued, writing or running was cut off by the restart. Tell its chat once and
    mark it interrupted_told, so the next start stays quiet. Returns how many were told."""
    root = workspace() / "videos"
    if not root.is_dir():
        return 0
    told = 0
    for path in sorted(root.glob("*/job.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("video job file %s can't be read; skipped", path)
            continue
        if not is_interrupted(data):
            continue
        slug = data.get("slug") or path.parent.name
        title = data.get("title") or slug
        text = f"The video about {title} was interrupted (Odie restarted). Ask me again to make it."
        try:
            await tell(slug, data.get("session_id"), text)
        except Exception:  # noqa: BLE001 (stays as it was, so the next start tries again)
            log.warning("couldn't tell the chat about interrupted video %s", slug, exc_info=True)
            continue
        data["status"] = "interrupted_told"
        save_json(path.parent, data)
        told += 1
    return told


def is_interrupted(data: dict) -> bool:
    """Was this job cut off by a restart? {"status": "running"} -> yes; {"status": "writing"} -> yes; {"status": "queued"} -> yes
    (the line was in memory); {"status": "done"}, "failed" or "interrupted_told" -> no (finished, or already told)."""
    return data.get("status") in INTERRUPTED_STATUSES
