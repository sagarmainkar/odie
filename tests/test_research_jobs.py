"""Research as a background job: the writing step is the research writer's focused turn (it takes the store from
the queue's hooks); the making step writes the accepted report to <job folder>/<slug>.md and hands it over as a file
card; the queue posts "The research about … is ready." with that card, says a failure in one line, and tells research
a restart cut off once."""
import json
from types import SimpleNamespace

import pytest
from google.adk.events.event_actions import EventActions

from odie import media
from odie.agent.tools.files import workspace
from odie.making import jobs, research
from odie.making import research_writer as writer
from odie.store.db import Store

FINDINGS = " ".join(["Kettles with a 1.7 litre jug boil a full load in about four minutes."] * 14)
REPORT = ("## The short answer\n\nA 1.7 litre steel kettle suits a family of four best.\n\n"
          f"## Findings\n\n{FINDINGS}\n\n## Sources\n\n- https://example.com/kettle-review\n")


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


async def submits(prompt, instruction, tools, timeout, follow_up=None):
    """A stand-in for the runner's focused turn: the writer submits the report at once, without searching."""
    [submit] = [tool for tool in tools if getattr(tool, "__name__", "") == "submit_research"]
    context = SimpleNamespace(actions=EventActions())
    await submit("Which kettle to buy", REPORT, tool_context=context)
    return ""


def topic_job(slug="kettles", topic="Kettles for a family of four", session_id="chat-1"):
    folder = workspace() / research.FOLDER / slug
    folder.mkdir(parents=True, exist_ok=True)
    return jobs.Job(kind="research", slug=slug, title=topic, topic=topic, brief="For Asha: under ₹3,000.",
                    session_id=session_id, folder=folder)


# Through the queue.

async def test_finished_research_is_posted_with_its_file_card_and_pushed(world, statuses):
    chat, pushes, _store = world
    job = topic_job()
    await jobs.run(job, browser=object(), turn=submits)
    [(text, session_id, posted)] = chat.posts
    assert (text, session_id) == ("The research about Which kettle to buy is ready.", "chat-1")
    [card] = posted
    assert card["kind"] == "file" and card["title"] == "Which kettle to buy" and card["filename"] == "kettles.md"
    path, saved = media.get(card["id"])
    assert path.read_text(encoding="utf-8") == f"# Which kettle to buy\n\n{REPORT}"
    assert pushes[0]["body"] == text and pushes[0]["tag"] == "research-kettles"
    assert statuses == ["writing", "making", "done"]
    assert (job.folder / "kettles.md").read_text(encoding="utf-8") == f"# Which kettle to buy\n\n{REPORT}"
    saved_job = json.loads((job.folder / "job.json").read_text())
    assert saved_job["kind"] == "research" and saved_job["status"] == "done" and "brief" not in saved_job
    assert (job.folder / "brief.md").read_text() == "For Asha: under ₹3,000.\n"


async def test_a_writer_that_fails_is_said_in_the_chat(world):
    chat, _pushes, _store = world

    async def talks(prompt, instruction, tools, timeout, follow_up=None):
        return "I'd rather chat."

    await jobs.run(topic_job(), browser=object(), turn=talks)
    [(text, _session_id, posted)] = chat.posts
    assert text == ("The research about Kettles for a family of four didn't finish: I couldn't write the report (the "
                    "writer stopped without one).")
    assert posted is None


async def test_the_writing_step_hands_the_job_and_the_queues_store_to_the_writer(world, monkeypatch):
    _chat, _pushes, store = world
    handed = {}

    async def stand_in_write(topic, brief, turn, store, transport=None):
        handed.update(topic=topic, brief=brief, turn=turn, store=store, transport=transport)
        return writer.Written(title="  Kettles  ", markdown=REPORT)

    monkeypatch.setattr(writer, "write", stand_in_write)
    job = topic_job()
    await research.write(job, "the turn", object())
    assert handed == {"topic": "Kettles for a family of four", "brief": "For Asha: under ₹3,000.", "turn": "the turn",
                      "store": store, "transport": None}
    assert job.title == "Kettles" and job.data == {"markdown": REPORT}


async def test_a_report_that_starts_with_its_own_top_heading_keeps_it(world):
    job = topic_job()
    job.title = "Kettles"
    job.data["markdown"] = "# Kettles, compared\n\nThe answer."
    card = await research.make(job, object(), None)
    assert (job.folder / "kettles.md").read_text(encoding="utf-8") == "# Kettles, compared\n\nThe answer.\n"
    assert card["filename"] == "kettles.md" and card["title"] == "Kettles"


def test_the_title_goes_on_top_only_when_the_report_has_no_top_heading():
    assert research.with_title("## The short answer\n\nYes.", "Kettles") == "# Kettles\n\n## The short answer\n\nYes.\n"
    assert research.with_title("\n# Kettles, compared\n\nYes.\n", "Kettles") == "# Kettles, compared\n\nYes.\n"


def test_research_is_a_built_in_kind_with_its_own_folder():
    assert "odie.making.research" in jobs.BUILT_IN_KINDS
    jobs.load_kinds()
    kind = jobs.KINDS["research"]
    assert kind is research.KIND and kind.word == "research" and kind.folder == "research"


async def test_research_a_restart_cut_off_is_told_once(world):
    chat, pushes, _store = world
    job = topic_job(slug="moon", topic="The moon landings")
    jobs.write_job(job, "writing")
    assert await jobs.recover() == 1
    [(text, session_id, _posted)] = chat.posts
    assert text == "The research about The moon landings was interrupted (Odie restarted). Ask me again to make it."
    assert session_id == "chat-1" and pushes[0]["tag"] == "research-moon"
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
