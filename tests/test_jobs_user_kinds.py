"""A user skill can make things in Odie's background queue: its tools.py puts a Kind into odie.making.jobs.KINDS when
it is imported. A job of that kind that a restart cut off must be told at the next start, like a video or a podcast,
so start-up imports the user's allowed skills before it looks for interrupted jobs."""
import json

import pytest

from odie.agent.tools.files import workspace
from odie.making import jobs
from odie.skills import registry
from odie.store.db import Store

SKILL_MD = """---
name: poems
description: Writes a poem in the background. Use when the user asks for a poem.
---
Call make_poem.
"""

# What a user skill's tools.py does to register its kind: a Kind in KINDS, set when the file is imported.
TOOLS_PY = '''
from odie.making import jobs


async def write(job, turn, browser):
    job.title = job.topic


async def make(job, browser, transport):
    return {}


jobs.KINDS["poem"] = jobs.Kind(word="poem", folder="poems", write=write, make=make)


def make_poem(topic: str) -> dict:
    """Make a poem about the topic."""
    return {"ok": True}


TOOLS = [make_poem]
'''


class Chat:
    """Stands in for the runner: keeps every post_message call as (text, session_id)."""

    def __init__(self):
        self.posts = []

    async def post_message(self, text, session_id=None, media=None, kind="system"):
        self.posts.append((text, session_id))


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A store, a chat to post to and no real pushes, everything under tmp_path; KINDS goes back as it was after."""
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    assert str(isolated_settings.config_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    chat = Chat()
    monkeypatch.setattr(jobs, "KINDS", dict(jobs.KINDS))  # the skill's kind never outlives this test
    monkeypatch.setattr(jobs, "send_to_all", lambda *args, **kwargs: 1)
    monkeypatch.setitem(jobs.hooks, "runner", chat)
    monkeypatch.setitem(jobs.hooks, "store", store)
    return store, chat, isolated_settings


def add_poem_skill(config_dir):
    folder = config_dir / "skills" / "poems"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (folder / "tools.py").write_text(TOOLS_PY, encoding="utf-8")


def allow_skill(store, name):
    """What the user's OK in Settings → Skills does: the skill's code is trusted at its current hash."""
    entry = next(e for e in registry.discover(store) if e.name == name)
    assert entry.status == "blocked"  # a user skill with code waits for the OK
    registry.trust(store, entry)


def cut_off_poem_job():
    """A poem job that was being made when Odie stopped: its job.json still says "making"."""
    folder = workspace() / "poems" / "sea"
    folder.mkdir(parents=True)
    job = {"status": "making", "kind": "poem", "title": "The sea", "session_id": "chat-1", "slug": "sea"}
    (folder / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return folder / "job.json"


async def test_a_job_of_a_user_skills_kind_that_a_restart_cut_off_is_told(world):
    store, chat, settings = world
    add_poem_skill(settings.config_dir)
    allow_skill(store, "poems")
    job_file = cut_off_poem_job()

    assert await jobs.recover(store) == 1  # what start-up calls

    told = "The poem about The sea was interrupted (Odie restarted). Ask me again to make it."
    assert chat.posts == [(told, "chat-1")]
    assert json.loads(job_file.read_text())["status"] == "interrupted_told"


async def test_a_skill_the_user_has_not_allowed_never_runs_and_its_job_waits(world):
    store, chat, settings = world
    add_poem_skill(settings.config_dir)  # never allowed
    job_file = cut_off_poem_job()

    assert await jobs.recover(store) == 0

    assert "poem" not in jobs.KINDS
    assert chat.posts == []
    assert json.loads(job_file.read_text())["status"] == "making"  # told once it is allowed and Odie starts again
