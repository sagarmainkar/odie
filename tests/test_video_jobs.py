"""The video job queue: one render at a time, the finished video posted to the chat it was asked in with a push, a
failure said in that chat, and a job that a restart cut off told once."""
import asyncio
import json

import pytest

from odie import voice
from odie.browser.engine import BrowserError
from odie.store.db import Store
from odie.video import encode, jobs
from tests.test_media import make_wav
from tests.test_video_encode import jpeg


class Chat:
    """Stands in for the runner: keeps every post_message call as (text, session_id, media)."""

    def __init__(self):
        self.posts = []

    async def post_message(self, text, session_id=None, media=None):
        self.posts.append((text, session_id, media))


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A chat to post to, the pushes sent, and a fresh queue; everything on disk under tmp_path."""
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    chat = Chat()
    pushes = []

    def record_push(store, title, body, url="/", tag=None):
        pushes.append({"title": title, "body": body, "url": url, "tag": tag})
        return 1

    monkeypatch.setattr(jobs, "send_to_all", record_push)
    monkeypatch.setitem(jobs.hooks, "runner", chat)
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(jobs, "_queue", None)
    monkeypatch.setattr(jobs, "_worker", None)
    monkeypatch.setattr(jobs, "_waiting", 0)
    yield chat, pushes, store
    if jobs._worker is not None:
        jobs._worker.cancel()


def make_job(slug="attention", title="Attention", session_id="chat-1"):
    from odie.agent.tools.files import workspace
    folder = workspace() / "videos" / slug
    folder.mkdir(parents=True, exist_ok=True)
    return jobs.Job(slug=slug, title=title, session_id=session_id, narration=["First scene.", "Second scene."],
                    body="<div></div>", voice_name="", folder=folder)


async def stand_in_narrate(store, narration, voice_name="", transport=None):
    return make_wav(2.0), [1.0, 0.5]


async def stand_in_render(browser, body, timings, folder, fps, tabs, progress=None):
    """A real, tiny segment file (15 red frames), so the real mux and probe have something to join."""
    path = folder / "segment-0.mp4"
    async with encode.Segment(path, fps=10) as segment:
        for _ in range(15):
            await segment.add(jpeg("red"))
    return [path]


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(jobs, "narrate", stand_in_narrate)
    monkeypatch.setattr(jobs, "render", stand_in_render)


def read_status(job):
    return json.loads((job.folder / "job.json").read_text())


async def test_a_finished_video_is_posted_to_its_chat_and_pushed(world, fast):
    chat, pushes, _store = world
    job = make_job()
    await jobs.run(job, browser=object())
    [(text, session_id, media)] = chat.posts
    assert (text, session_id) == ("The video about Attention is ready.", "chat-1")
    assert len(media) == 1 and media[0]["kind"] == "video"
    assert pushes[0]["body"] == text and pushes[0]["tag"] == "video-attention" and pushes[0]["url"] == "/#chat"
    assert (job.folder / "attention.mp4").exists()
    assert (job.folder / "narration.wav").exists() and "window.__timings" in (job.folder / "page.html").read_text()
    assert read_status(job)["status"] == "done"


async def test_the_page_is_timed_from_the_spoken_lengths(world, fast, monkeypatch):
    seen = {}

    async def watching_render(browser, body, timings, folder, fps, tabs, progress=None):
        seen["timings"] = timings
        return await stand_in_render(browser, body, timings, folder, fps, tabs)

    monkeypatch.setattr(jobs, "render", watching_render)
    await jobs.run(make_job(), browser=object())
    assert seen["timings"] == {"starts": [0.0, 1.5], "lengths": [1.0, 0.5]}


async def test_a_voice_that_cant_speak_is_said_in_the_chat(world, monkeypatch):
    chat, pushes, _store = world

    async def silent_voice(store, narration, voice_name="", transport=None):
        raise voice.VoiceUnavailable("Odie's local voice isn't running")

    monkeypatch.setattr(jobs, "narrate", silent_voice)
    job = make_job()
    await jobs.run(job, browser=object())
    [(text, session_id, media)] = chat.posts
    assert text == "The video about Attention didn't finish: Odie's local voice isn't running."
    assert session_id == "chat-1" and media is None
    assert pushes[0]["body"] == text
    assert read_status(job)["status"] == "failed" and "isn't running" in read_status(job)["error"]


async def test_a_browser_error_keeps_its_own_words(world, fast, monkeypatch):
    chat, _pushes, _store = world

    async def broken_render(browser, body, timings, folder, fps, tabs, progress=None):
        raise BrowserError("no browser is installed\nsecond line that stays out of the chat")

    monkeypatch.setattr(jobs, "render", broken_render)
    await jobs.run(make_job(), browser=object())
    assert chat.posts[0][0] == "The video about Attention didn't finish: no browser is installed."


async def test_anything_unexpected_is_a_plain_sentence_and_logged(world, fast, monkeypatch, caplog):
    chat, _pushes, _store = world

    async def odd_render(browser, body, timings, folder, fps, tabs, progress=None):
        raise KeyError("/Users/someone/private/path")

    monkeypatch.setattr(jobs, "render", odd_render)
    await jobs.run(make_job(), browser=object())
    assert chat.posts[0][0] == "The video about Attention didn't finish: something went wrong (see Odie's log)."
    assert "private/path" not in chat.posts[0][0]
    assert any("Attention" in record.getMessage() or record.exc_info for record in caplog.records)


async def test_a_file_without_sound_is_a_failure_not_a_video(world, fast, monkeypatch):
    chat, _pushes, _store = world

    async def mute_probe(path):
        return {"seconds": 3.0, "video": True, "audio": False}

    monkeypatch.setattr(jobs, "probe", mute_probe)
    await jobs.run(make_job(), browser=object())
    assert chat.posts[0][0].startswith("The video about Attention didn't finish: ")
    assert chat.posts[0][2] is None


def test_the_one_line_for_the_chat():
    assert jobs.one_line(voice.VoiceUnavailable("Odie's local voice isn't running.")) == "Odie's local voice isn't running"
    assert jobs.one_line(encode.EncodeError("x" * 500)) == "x" * 200
    assert jobs.one_line(ValueError("secret detail")) == "something went wrong (see Odie's log)"


async def test_a_push_that_fails_does_not_lose_the_post(world, fast, monkeypatch):
    chat, _pushes, _store = world

    def broken_push(*args, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(jobs, "send_to_all", broken_push)
    job = make_job()
    await jobs.run(job, browser=object())
    assert chat.posts[0][0] == "The video about Attention is ready." and read_status(job)["status"] == "done"


async def test_a_second_video_queues(world, monkeypatch):
    started = []
    release = asyncio.Event()

    async def slow_run(job, browser=None, transport=None):
        started.append(job.slug)
        await release.wait()

    monkeypatch.setattr(jobs, "run", slow_run)
    job_a, job_b = make_job("a", "A"), make_job("b", "B")
    assert jobs.queue_position() == 0
    assert jobs.submit(job_a) == 1 and jobs.submit(job_b) == 2
    assert jobs.queue_position() == 2
    assert read_status(job_b)["status"] == "queued"
    await asyncio.sleep(0.05)
    assert started == ["a"]          # one render at a time: b waits
    release.set()
    await asyncio.sleep(0.05)
    assert started == ["a", "b"] and jobs.queue_position() == 0


async def test_one_failing_job_does_not_stop_the_next(world, monkeypatch):
    ran = []

    async def sometimes_broken_run(job, browser=None, transport=None):
        ran.append(job.slug)
        if job.slug == "a":
            raise RuntimeError("boom")

    monkeypatch.setattr(jobs, "run", sometimes_broken_run)
    jobs.submit(make_job("a", "A"))
    jobs.submit(make_job("b", "B"))
    await asyncio.sleep(0.05)
    assert ran == ["a", "b"] and jobs.queue_position() == 0


async def test_an_interrupted_job_is_told_once(world):
    chat, pushes, _store = world
    running = make_job("attention", "Attention")
    (running.folder / "job.json").write_text('{"status": "running", "title": "Attention", "session_id": "chat-1"}')
    queued = make_job("waiting", "Waiting")
    (queued.folder / "job.json").write_text('{"status": "queued", "title": "Waiting", "session_id": "chat-2"}')
    finished = make_job("old", "Old")
    (finished.folder / "job.json").write_text('{"status": "done", "title": "Old", "session_id": "chat-3"}')

    assert await jobs.recover() == 2 and await jobs.recover() == 0
    texts = sorted((text, session_id) for text, session_id, _media in chat.posts)
    assert texts == [
        ("The video about Attention was interrupted (Odie restarted). Ask me again to make it.", "chat-1"),
        ("The video about Waiting was interrupted (Odie restarted). Ask me again to make it.", "chat-2"),
    ]
    assert len(pushes) == 2 and {p["tag"] for p in pushes} == {"video-attention", "video-waiting"}
    assert read_status(running)["status"] == "interrupted_told"
    assert read_status(finished)["status"] == "done"


async def test_recover_with_no_videos_folder_does_nothing(world):
    assert await jobs.recover() == 0


async def test_stopping_mid_render_posts_nothing_and_recover_tells_it_as_interrupted(world, fast, monkeypatch):
    chat, pushes, _store = world

    async def render_that_never_ends(browser, body, timings, folder, fps, tabs, progress=None):
        await asyncio.Event().wait()

    monkeypatch.setattr(jobs, "render", render_that_never_ends)
    job = make_job()
    jobs.submit(job)
    await asyncio.sleep(0.2)                      # the worker has taken the job and is waiting inside render
    assert read_status(job)["status"] == "running"
    await jobs.stop()
    assert read_status(job)["status"] == "running" and chat.posts == [] and pushes == []
    assert await jobs.recover() == 1
    assert chat.posts == [("The video about Attention was interrupted (Odie restarted). Ask me again to make it.",
                           "chat-1", None)]


async def test_stop_with_nothing_running_is_fine(world):
    await jobs.stop()


async def test_a_failure_after_rendering_is_told_too(world, fast, monkeypatch):
    chat, pushes, _store = world

    def full_disk(path, title=""):
        raise OSError("No space left on device")

    monkeypatch.setattr(jobs, "hand_over", full_disk)
    job = make_job()
    await jobs.run(job, browser=object())
    assert chat.posts == [("The video about Attention didn't finish: something went wrong (see Odie's log).",
                           "chat-1", None)]
    assert len(pushes) == 1 and read_status(job)["status"] == "failed"
