"""The shared queue for everything Odie makes in the background (odie.making.jobs), driven by a stand-in kind: a
"note" whose writing step fills in a title and a text and whose making step saves a file. Every message names the
kind ("The note about … is ready."), the statuses run queued → writing → making → done, and a job.json from before
kinds existed (status "running", no kind) is told once, as a video."""
import asyncio
import json

import pytest

from odie.agent.tools.files import workspace
from odie.making import jobs
from odie.store.db import Store


class Chat:
    """Stands in for the runner: keeps every post_message call as (text, session_id, media), and has a focused turn
    the queue hands to the writing step."""

    def __init__(self):
        self.posts = []
        self.focused_turn = "the runner's focused turn"

    async def post_message(self, text, session_id=None, media=None):
        self.posts.append((text, session_id, media))


class NoteFailed(Exception):
    """An error the note kind writes for the user, so its words are shown."""


class Notes:
    """The stand-in kind's two steps, recording what they were handed. `fail_with` makes the making step raise."""

    def __init__(self):
        self.written = []
        self.made = []
        self.fail_with = None

    async def write(self, job, turn, browser):
        self.written.append((job.topic, job.brief, turn, browser))
        job.title = jobs.title_after_writing("  A note on tides ", job)
        job.data["text"] = "The moon pulls the sea."

    async def make(self, job, browser, transport):
        self.made.append((job.slug, browser, transport))
        if self.fail_with is not None:
            raise self.fail_with
        path = job.folder / "note.txt"
        path.write_text(job.data["text"])
        return {"kind": "note", "url": f"/files/{path.name}"}


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A chat to post to, the pushes sent, a fresh queue and the stand-in "note" kind; everything under tmp_path."""
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    chat = Chat()
    pushes = []

    def record_push(store, title, body, url="/", tag=None):
        pushes.append({"title": title, "body": body, "url": url, "tag": tag})
        return 1

    notes = Notes()
    monkeypatch.setattr(jobs, "send_to_all", record_push)
    monkeypatch.setitem(jobs.hooks, "runner", chat)
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(jobs, "_queue", None)
    monkeypatch.setattr(jobs, "_worker", None)
    monkeypatch.setattr(jobs, "_waiting", 0)
    kind = jobs.Kind(word="note", folder="notes", write=notes.write, make=notes.make, known_errors=(NoteFailed,))
    monkeypatch.setitem(jobs.KINDS, "note", kind)
    yield chat, pushes, notes
    if jobs._worker is not None:
        jobs._worker.cancel()


def note_job(slug="tides", title="Tides", session_id="chat-1"):
    folder = workspace() / "notes" / slug
    folder.mkdir(parents=True, exist_ok=True)
    return jobs.Job(kind="note", slug=slug, title=title, session_id=session_id, folder=folder, topic="tides",
                    minutes=1, brief="For Asha: the moon first.")


def read_status(folder):
    return json.loads((folder / "job.json").read_text())


@pytest.fixture
def statuses(monkeypatch):
    """Every status job.json is given, in order."""
    seen = []
    real = jobs.write_job

    def recording(job, status, error=""):
        seen.append(status)
        real(job, status, error)

    monkeypatch.setattr(jobs, "write_job", recording)
    return seen


async def wait_until_idle():
    for _ in range(100):
        if jobs.queue_position() == 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the queue never emptied")


async def test_a_second_kind_runs_through_the_queue_end_to_end(world, statuses, monkeypatch):
    chat, pushes, notes = world
    browser = object()
    monkeypatch.setattr(jobs, "render_browser", lambda: browser)
    job = note_job()
    assert jobs.submit(job) == 1
    await wait_until_idle()

    assert statuses == ["queued", "writing", "making", "done"]
    assert notes.written == [("tides", "For Asha: the moon first.", "the runner's focused turn", browser)]
    assert notes.made == [("tides", browser, None)]
    assert chat.posts == [("The note about A note on tides is ready.", "chat-1",
                           [{"kind": "note", "url": "/files/note.txt"}])]
    assert pushes == [{"title": "Odie", "body": "The note about A note on tides is ready.", "url": "/#chat",
                       "tag": "note-tides"}]
    data = read_status(job.folder)
    assert data["status"] == "done" and data["kind"] == "note" and data["title"] == "A note on tides"
    assert "brief" not in data and "For Asha" not in json.dumps(data)


async def test_the_queue_doesnt_inherit_the_submitting_chat_turns_context(world, monkeypatch):
    """The worker starts inside whichever chat turn submits first. A private chat queues a job first; a later job
    from a public chat must not see that chat's words or private sites, so the worker starts in an empty context."""
    from odie.agent import turn

    chat, pushes, notes = world
    monkeypatch.setattr(jobs, "render_browser", lambda: object())
    seen = []
    real_make = notes.make

    async def make_and_look(job, browser, transport):
        seen.append((turn.USER_TEXT.get(), turn.PRIVATE.get(), turn.private_sites()))
        return await real_make(job, browser, transport)

    kind = jobs.Kind(word="note", folder="notes", write=notes.write, make=make_and_look)
    monkeypatch.setitem(jobs.KINDS, "note", kind)

    said = turn.USER_TEXT.set("make a podcast about tides")
    private = turn.PRIVATE.set({"amazon.in"})
    try:
        jobs.submit(note_job())
        await wait_until_idle()
    finally:
        turn.USER_TEXT.reset(said)
        turn.PRIVATE.reset(private)

    assert seen == [(None, None, set())]
    assert chat.posts[0][0] == "The note about A note on tides is ready."


async def test_a_kind_may_say_more_than_ready(world, monkeypatch):
    chat, pushes, notes = world
    monkeypatch.setattr(jobs, "render_browser", lambda: object())

    def ready_text(job):
        return f"{jobs.ready_line('note', job.title)}\n\n{job.data['text']}"

    kind = jobs.Kind(word="note", folder="notes", write=notes.write, make=notes.make, ready_text=ready_text)
    monkeypatch.setitem(jobs.KINDS, "note", kind)
    await jobs.run(note_job())
    [(text, _session_id, media)] = chat.posts
    assert text == "The note about A note on tides is ready.\n\nThe moon pulls the sea."
    assert media == [{"kind": "note", "url": "/files/note.txt"}]


async def test_a_failure_names_the_kind_and_keeps_its_known_words(world, statuses):
    chat, pushes, notes = world
    notes.fail_with = NoteFailed("The paper ran out.\nmore detail that stays out")
    job = note_job()
    await jobs.run(job, browser=object(), turn="a turn")
    assert chat.posts == [("The note about A note on tides didn't finish: The paper ran out.", "chat-1", None)]
    assert pushes[0]["tag"] == "note-tides"
    assert statuses == ["writing", "making", "failed"]
    assert read_status(job.folder)["error"] == "The paper ran out"


async def test_an_error_the_kind_doesnt_know_is_a_plain_sentence(world):
    chat, _pushes, notes = world
    notes.fail_with = KeyError("/Users/someone/private/path")
    await jobs.run(note_job(), browser=object(), turn="a turn")
    assert chat.posts[0][0] == "The note about A note on tides didn't finish: something went wrong (see Odie's log)."


async def test_an_interrupted_job_names_its_kind(world):
    chat, pushes, _notes = world
    making = note_job("tides", "Tides")
    (making.folder / "job.json").write_text(
        '{"status": "making", "kind": "note", "title": "Tides", "session_id": "chat-1", "slug": "tides"}')
    assert await jobs.recover() == 1 and await jobs.recover() == 0
    assert chat.posts == [("The note about Tides was interrupted (Odie restarted). Ask me again to make it.",
                           "chat-1", None)]
    assert pushes[0]["tag"] == "note-tides"
    assert read_status(making.folder)["status"] == "interrupted_told"


async def test_a_job_json_from_before_kinds_saying_running_is_told_once_as_a_video(world):
    chat, pushes, _notes = world
    folder = workspace() / "videos" / "attention"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text('{"status": "running", "title": "Attention", "session_id": "chat-1"}')
    assert await jobs.recover() == 1
    assert await jobs.recover() == 0
    assert chat.posts == [("The video about Attention was interrupted (Odie restarted). Ask me again to make it.",
                           "chat-1", None)]
    assert len(pushes) == 1 and pushes[0]["tag"] == "video-attention"
    assert read_status(folder)["status"] == "interrupted_told"


@pytest.mark.parametrize("status", ["queued", "writing", "making", "running"])
def test_every_unfinished_status_counts_as_interrupted(status):
    assert jobs.is_interrupted({"status": status})


@pytest.mark.parametrize("status", ["done", "failed", "interrupted_told"])
def test_finished_or_told_statuses_dont(status):
    assert not jobs.is_interrupted({"status": status})


async def test_a_job_already_written_goes_straight_to_making(world, statuses, monkeypatch):
    chat, _pushes, notes = world
    monkeypatch.setitem(jobs.KINDS, "note", jobs.Kind(word="note", folder="notes", write=notes.write,
                                                      make=notes.make, needs_writing=lambda job: False))
    job = note_job()
    job.data["text"] = "Already written."
    await jobs.run(job, browser=object())
    assert notes.written == [] and statuses == ["making", "done"]
    assert (job.folder / "note.txt").read_text() == "Already written."
    assert chat.posts[0][0] == "The note about Tides is ready."


def test_the_one_line_keeps_the_words_of_the_kinds_known_errors_only():
    assert jobs.one_line(NoteFailed("The paper ran out."), (NoteFailed,)) == "The paper ran out"
    assert jobs.one_line(NoteFailed("The paper ran out."), ()) == "something went wrong (see Odie's log)"
    assert jobs.one_line(ValueError("secret"), (NoteFailed,)) == "something went wrong (see Odie's log)"
