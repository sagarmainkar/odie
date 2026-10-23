"""The podcast as a background job: the making step speaks each turn in its host's voice (a woman first, then a man,
from the Settings engine) and saves one WAV as the chat's podcast player; the queue posts "The podcast about … is
ready." with that player, says a failure in one line, and tells a podcast a restart cut off once."""
import json
from types import SimpleNamespace

import httpx
import pytest
from google.adk.events.event_actions import EventActions

from odie import media, voice
from odie.agent.tools.files import workspace
from odie.making import jobs, podcast
from odie.making import podcast_writer as writer
from odie.store.db import Store
from tests.test_media import make_wav

SCRIPT = "\n".join(f"Host {'B' if n % 2 else 'A'}: {' '.join(['tides'] * 27)} end." for n in range(10))  # 280 words


class Chat:
    """Stands in for the runner: keeps every post_message call as (text, session_id, media)."""

    def __init__(self):
        self.posts = []

    async def post_message(self, text, session_id=None, media=None, kind="system"):
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


def kokoro(seen, seconds=0.5):
    """Odie's local voice, answering every turn with `seconds` of sound and recording what it was asked."""
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=make_wav(seconds))
    return httpx.MockTransport(handler)


def down():
    def handler(request):
        raise httpx.ConnectError("Connection refused")
    return httpx.MockTransport(handler)


async def submits(prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
    """A stand-in for the runner's focused turn: the writer submits the script at once."""
    [submit] = tools
    context = SimpleNamespace(actions=EventActions())
    await submit("Tides, explained", SCRIPT, tool_context=context)
    return ""


def topic_job(slug="tides", topic="How tides work", session_id="chat-1"):
    folder = workspace() / podcast.FOLDER / slug
    folder.mkdir(parents=True, exist_ok=True)
    return jobs.Job(kind="podcast", slug=slug, title=topic, topic=topic, minutes=2,
                    brief="For Asha, who sails.", session_id=session_id, folder=folder)


# The making step: the existing podcast audio, now called by the job.

async def test_speak_podcast_gives_the_first_host_a_womans_voice_and_saves_the_player(world):
    _chat, _pushes, store = world
    seen = []
    turns = [("Asha", "Welcome back!"), ("Rohan", "Today, our session."), ("Asha", "So where do we start?"),
             ("Rohan", "With the basics.")]
    m = await podcast.speak_podcast(store, turns, "Our session", transport=kokoro(seen, 0.5))
    assert m["kind"] == "podcast" and m["title"] == "Our session" and m["mime"] == "audio/wav"
    assert m["hosts"] == [{"name": "Asha", "voice": "Heart", "group": "female"},
                          {"name": "Rohan", "voice": "Michael", "group": "male"}]
    assert [b["voice"] for b in seen] == ["af_heart", "am_michael", "af_heart", "am_michael"]
    assert seen[2]["text"] == "So where do we start?"
    assert [(t["host"], t["start"]) for t in m["transcript"]] == [
        ("Asha", 0.0), ("Rohan", 0.8), ("Asha", 1.6), ("Rohan", 2.4)]
    assert m["duration"] == 2.9  # four half-second turns and three 300 ms gaps
    assert len(m["peaks"]) == 48
    path, saved = media.get(m["id"])
    assert path.read_bytes()[:4] == b"RIFF" and saved == m  # the chat reads the same description from the sidecar


async def test_the_voices_follow_the_settings_accent(world):
    _chat, _pushes, store = world
    voice.set_tts(store, engine="kokoro", voice="bf_emma")
    seen = []
    await podcast.speak_podcast(store, [("Host A", "Hello."), ("Host B", "Hi.")], "Tides", transport=kokoro(seen))
    assert [b["voice"] for b in seen] == ["bf_emma", "bm_george"]


async def test_a_voice_that_doesnt_answer_is_said_in_one_line(world):
    _chat, _pushes, store = world
    with pytest.raises(voice.VoiceUnavailable) as e:
        await podcast.speak_podcast(store, [("Host A", "Hello."), ("Host B", "Hi.")], "Tides", transport=down())
    assert str(e.value) == "Odie's voice didn't answer (Settings → Voice): Connection refused"


# Through the queue.

async def test_a_finished_podcast_is_posted_with_its_player_and_pushed(world, statuses):
    chat, pushes, _store = world
    job = topic_job()
    seen = []
    await jobs.run(job, browser=object(), transport=kokoro(seen, 0.5), turn=submits)
    [(text, session_id, posted)] = chat.posts
    assert (text, session_id) == ("The podcast about Tides, explained is ready.", "chat-1")
    [m] = posted
    assert m["kind"] == "podcast" and m["title"] == "Tides, explained"
    assert [t["host"] for t in m["transcript"]][:2] == ["Host A", "Host B"] and len(m["transcript"]) == 10
    assert [b["voice"] for b in seen][:2] == ["af_heart", "am_michael"]
    assert pushes[0]["body"] == text and pushes[0]["tag"] == "podcast-tides" and pushes[0]["url"] == "/#chat"
    assert statuses == ["writing", "making", "done"]
    saved = json.loads((job.folder / "job.json").read_text())
    assert saved["kind"] == "podcast" and saved["status"] == "done" and "brief" not in saved
    assert (job.folder / "brief.md").read_text() == "For Asha, who sails.\n"


async def test_a_voice_that_cant_speak_is_said_in_the_chat(world):
    chat, _pushes, _store = world
    job = topic_job()
    await jobs.run(job, browser=object(), transport=down(), turn=submits)
    [(text, _session_id, posted)] = chat.posts
    assert text == ("The podcast about Tides, explained didn't finish: Odie's voice didn't answer (Settings → Voice): "
                    "Connection refused.")
    assert posted is None
    assert json.loads((job.folder / "job.json").read_text())["status"] == "failed"


async def test_a_writer_that_fails_is_said_in_the_chat(world):
    chat, _pushes, _store = world

    async def talks(prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
        return "I'd rather chat."

    await jobs.run(topic_job(), browser=object(), turn=talks)
    [(text, _session_id, _posted)] = chat.posts
    assert text == ("The podcast about How tides work didn't finish: I couldn't write the podcast's script (the writer "
                    "stopped without one).")


async def test_the_writing_step_hands_the_job_to_the_writer(world, monkeypatch):
    handed = {}

    async def stand_in_write(topic, minutes, brief, turn):
        handed.update(topic=topic, minutes=minutes, brief=brief, turn=turn)
        return writer.Written(title="  Tides  ", turns=[("Host A", "Hi."), ("Host B", "Hello.")])

    monkeypatch.setattr(writer, "write", stand_in_write)
    job = topic_job()
    await podcast.write(job, "the turn", object())
    assert handed == {"topic": "How tides work", "minutes": 2, "brief": "For Asha, who sails.", "turn": "the turn"}
    assert job.title == "Tides" and job.data == {"turns": [("Host A", "Hi."), ("Host B", "Hello.")]}


def test_the_podcast_is_a_built_in_kind_with_its_own_folder():
    assert "odie.making.podcast" in jobs.BUILT_IN_KINDS
    jobs.load_kinds()
    kind = jobs.KINDS["podcast"]
    assert kind is podcast.KIND and kind.word == "podcast" and kind.folder == "podcasts"
    assert voice.VoiceUnavailable in kind.known_errors


async def test_a_podcast_a_restart_cut_off_is_told_once(world):
    chat, pushes, _store = world
    job = topic_job(slug="moon", topic="The moon")
    jobs.write_job(job, "writing")
    assert await jobs.recover() == 1
    [(text, session_id, _posted)] = chat.posts
    assert text == "The podcast about The moon was interrupted (Odie restarted). Ask me again to make it."
    assert session_id == "chat-1" and pushes[0]["tag"] == "podcast-moon"
    assert await jobs.recover() == 0  # told once


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
