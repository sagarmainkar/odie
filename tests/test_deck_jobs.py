"""The deck as a background job: the writing step is the deck writer; the making step builds the accepted Markdown with
the existing deck code (odie.decks.build.make_deck: the PowerPoint, and with a browser the PDF and previews; no
browser in tests, as tests/test_decks_build.py does); the queue posts "The deck about … is ready." with the deck card,
says a failure in one line, and tells a deck a restart cut off once."""
import json
from types import SimpleNamespace

import pytest
from google.adk.events.event_actions import EventActions

from odie import media
from odie.agent import turn
from odie.agent.tools.files import workspace
from odie.decks import build
from odie.making import deck, jobs
from odie.making import deck_writer as writer
from odie.store.db import Store

DECK = ("# Tides\nkicker: For Asha, who sails\nWhy the sea comes in twice a day\n\n"
        "# Two bulges\n- **The moon** — pulls\n")


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


def submits(markdown=DECK, title="Tides, explained", theme="minimal"):
    """A stand-in for the runner's focused turn: the writer submits this deck at once."""
    async def focused_turn(prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
        [submit] = tools
        context = SimpleNamespace(actions=EventActions())
        await submit(title, markdown, theme, tool_context=context)
        return ""
    return focused_turn


def topic_job(slug="tides", topic="How tides work", session_id="chat-1", data=None):
    folder = workspace() / deck.FOLDER / slug
    folder.mkdir(parents=True, exist_ok=True)
    if data is None:
        data = {"theme": "editorial", "earlier": "", "private": []}
    return jobs.Job(kind="deck", slug=slug, title=topic, topic=topic, brief="For Asha, who sails.",
                    session_id=session_id, folder=folder, data=data)


# Through the queue: the existing deck code builds it (no browser in tests: ODIE_BROWSER is off).

async def test_a_finished_deck_is_posted_with_its_card_and_pushed(world, statuses):
    chat, pushes, _store = world
    job = topic_job()
    await jobs.run(job, browser=object(), turn=submits())
    [(text, session_id, posted)] = chat.posts
    assert (text, session_id) == ("The deck about Tides, explained is ready.", "chat-1")
    [m] = posted
    assert m["filename"] == "Tides, explained.pptx" and m["deck"]["slides"] == 2 and m["deck"]["theme"] == "minimal"
    assert "need Chrome" in m["deck"]["note"]  # without a browser the PowerPoint still arrives
    assert media.get(m["id"])[1]["deck"]["slides"] == 2  # history reads the sidecar
    assert (workspace() / "Tides, explained.deck.md").read_text() == DECK  # where make_deck keeps decks, for revise
    assert pushes[0]["body"] == text and pushes[0]["tag"] == "deck-tides" and pushes[0]["url"] == "/#chat"
    assert statuses == ["writing", "making", "done"]
    saved = json.loads((job.folder / "job.json").read_text())
    assert saved["kind"] == "deck" and saved["status"] == "done" and "brief" not in saved
    assert (job.folder / "brief.md").read_text() == "For Asha, who sails.\n"


async def test_the_make_step_builds_the_written_deck_with_its_theme(world, monkeypatch):
    seen = {}

    async def stand_in(markdown, title="", theme_name="editorial", browser="default"):
        seen.update(markdown=markdown, title=title, theme=theme_name, browser=browser)
        return {"result": "Made it.", "media": {"id": "m1", "deck": {"slides": 2}}}

    monkeypatch.setattr(build, "make_deck", stand_in)
    job = topic_job()
    job.title = "Tides"
    job.data.update(markdown=DECK, theme="bold")
    got = await deck.make(job, object(), None)
    assert got == {"id": "m1", "deck": {"slides": 2}}
    assert seen == {"markdown": DECK, "title": "Tides", "theme": "bold", "browser": "default"}  # its own browser


async def test_a_deck_that_cant_be_built_is_said_in_the_chat(world, monkeypatch):
    chat, _pushes, _store = world

    def broken(*args, **kwargs):
        raise ValueError("max() iterable argument is empty")

    monkeypatch.setattr(build, "build_pptx", broken)
    job = topic_job()
    await jobs.run(job, browser=object(), turn=submits())
    [(text, _session_id, posted)] = chat.posts
    assert text == ("The deck about Tides, explained didn't finish: The deck couldn't be built (ValueError: max() "
                    "iterable argument is empty). Simplify the slide that has it, or try again.")
    assert posted is None
    assert json.loads((job.folder / "job.json").read_text())["status"] == "failed"


async def test_a_writer_that_fails_is_said_in_the_chat(world):
    chat, _pushes, _store = world

    async def talks(prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
        return "I'd rather chat."

    await jobs.run(topic_job(), browser=object(), turn=talks)
    [(text, _session_id, _posted)] = chat.posts
    assert text == ("The deck about How tides work didn't finish: I couldn't write the deck (the writer stopped "
                    "without one).")


async def test_the_writing_step_hands_the_job_to_the_writer(world, monkeypatch):
    handed = {}

    async def stand_in_write(topic, brief, theme, turn, earlier="", title=""):
        handed.update(topic=topic, brief=brief, theme=theme, turn=turn, earlier=earlier, title=title)
        return writer.Written(title="  Tides  ", markdown=DECK, theme="warm")

    monkeypatch.setattr(writer, "write", stand_in_write)
    job = topic_job(data={"theme": "minimal", "earlier": "# Old\n", "private": []})
    job.title = "Old"
    await deck.write(job, "the turn", object())
    assert handed == {"topic": "How tides work", "brief": "For Asha, who sails.", "theme": "minimal",
                      "turn": "the turn", "earlier": "# Old\n", "title": "Old"}
    assert job.title == "Tides" and job.data["markdown"] == DECK and job.data["theme"] == "warm"


async def test_a_private_chats_deck_is_built_as_private_and_a_later_one_is_not(world, monkeypatch):
    seen = []

    async def fetch_all(refs):
        seen.append(turn.private_sites())
        return {}, []

    monkeypatch.setattr(build, "fetch_all", fetch_all)
    private = topic_job(slug="orders", data={"theme": "editorial", "earlier": "", "private": ["amazon.in"],
                                             "markdown": DECK})
    public = topic_job(slug="tides", data={"theme": "editorial", "earlier": "", "private": [], "markdown": DECK})
    token = turn.PRIVATE.set({"amazon.in"})  # the queue's worker may have been started from a private chat
    try:
        await deck.make(private, object(), None)
        await deck.make(public, object(), None)
    finally:
        turn.PRIVATE.reset(token)
    assert seen == [{"amazon.in"}, set()]


PHOTO_DECK = DECK + "\n# The moon\nimage: https://example.com/moon.jpg (credit: NASA)\n"


def photo_job(private):
    """A deck job whose writer was given the moon photo's address in the brief."""
    folder = workspace() / deck.FOLDER / "moon"
    folder.mkdir(parents=True, exist_ok=True)
    data = {"theme": "editorial", "earlier": "", "private": private}
    return jobs.Job(kind="deck", slug="moon", title="Tides", topic="How tides work", session_id="chat-1",
                    brief="For Asha. Photo: https://example.com/moon.jpg (credit: NASA)", folder=folder, data=data)


async def test_a_private_chats_deck_with_web_photos_says_why_they_are_missing(world, monkeypatch):
    chat, pushes, _store = world

    async def none_fetched(refs):
        return {}, [ref for ref, _credit in refs]

    monkeypatch.setattr(build, "fetch_all", none_fetched)
    await jobs.run(photo_job(["amazon.in"]), browser=object(), turn=submits(markdown=PHOTO_DECK, title="Tides"))
    [(text, _session_id, posted)] = chat.posts
    assert text == ("The deck about Tides is ready. It was built without its web photos, because this chat is "
                    "private.")
    assert posted and pushes[0]["body"] == text


def test_the_photo_sentence_needs_both_a_private_chat_and_web_photos():
    private_with_photos = photo_job(["amazon.in"])
    private_with_photos.data["markdown"] = PHOTO_DECK
    private_without = photo_job(["amazon.in"])
    private_without.data["markdown"] = DECK
    public_with_photos = photo_job([])
    public_with_photos.data["markdown"] = PHOTO_DECK
    local_photo_only = photo_job(["amazon.in"])
    local_photo_only.data["markdown"] = DECK + "\n# A screenshot\nimage: screenshot:abc123\n"

    assert deck.KIND.ready_text(private_with_photos).endswith("because this chat is private.")
    assert deck.KIND.ready_text(private_without) == "The deck about Tides is ready."
    assert deck.KIND.ready_text(public_with_photos) == "The deck about Tides is ready."
    assert deck.KIND.ready_text(local_photo_only) == "The deck about Tides is ready."  # fetched in any chat


async def test_a_second_revision_revises_the_first_revision_not_the_original(world, monkeypatch):
    from odie.skills.documents import tools
    queued = []

    def queue(job):
        queued.append(job)
        return 1

    monkeypatch.setattr(jobs, "submit", queue)
    prompts = []

    def writes(markdown):
        """The writer, recording its prompt and submitting `markdown` under the title Tides."""
        async def focused_turn(prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
            prompts.append(prompt)
            [submit] = tools
            await submit("Tides", markdown, "minimal", tool_context=SimpleNamespace(actions=EventActions()))
            return ""
        return focused_turn

    original = "# Tides\n- the original\n"
    first = "# Tides\n- the first revision\n"
    second = "# Tides\n- the second revision\n"
    await tools.make_deck("Tides")
    await jobs.run(queued[-1], browser=object(), turn=writes(original))
    await tools.make_deck("Tides, shorter", brief="Make it shorter.", revise="Tides")
    await jobs.run(queued[-1], browser=object(), turn=writes(first))
    await tools.make_deck("Tides, shorter still", brief="Shorter still.", revise="Tides")
    await jobs.run(queued[-1], browser=object(), turn=writes(second))

    assert (workspace() / "Tides (2).deck.md").read_text() == first  # make_deck never overwrites the original
    assert queued[2].data["earlier"] == first
    assert first.strip() in prompts[2] and original.strip() not in prompts[2]
    assert (workspace() / "Tides (3).deck.md").read_text() == second


def test_the_deck_is_a_built_in_kind_with_its_own_folder():
    assert "odie.making.deck" in jobs.BUILT_IN_KINDS
    jobs.load_kinds()
    kind = jobs.KINDS["deck"]
    assert kind is deck.KIND and kind.word == "deck" and kind.folder == "decks"
    assert deck.DeckNotBuilt in kind.known_errors


async def test_a_deck_a_restart_cut_off_is_told_once(world):
    chat, pushes, _store = world
    job = topic_job(slug="moon", topic="The moon")
    jobs.write_job(job, "making")
    assert await jobs.recover() == 1
    [(text, session_id, _posted)] = chat.posts
    assert text == "The deck about The moon was interrupted (Odie restarted). Ask me again to make it."
    assert session_id == "chat-1" and pushes[0]["tag"] == "deck-moon"
    assert await jobs.recover() == 0  # told once


async def test_a_deck_queued_behind_a_podcast_is_second_and_both_are_posted_with_their_word(world, monkeypatch):
    chat, _pushes, _store = world
    from odie.making import podcast

    async def podcast_made(job, browser, transport):
        return {"id": "p1", "kind": "podcast"}

    async def podcast_written(job, turn, browser):
        job.title = "Moon"

    async def deck_written(job, turn, browser):
        job.data["markdown"] = DECK

    async def no_photos(refs):
        return {}, []

    monkeypatch.setattr(podcast.KIND, "write", podcast_written)
    monkeypatch.setattr(podcast.KIND, "make", podcast_made)
    monkeypatch.setattr(deck.KIND, "write", deck_written)
    monkeypatch.setattr(build, "fetch_all", no_photos)
    monkeypatch.setattr(jobs, "render_browser", lambda: object())
    chat.focused_turn = "the runner's focused turn"  # handed to the (stand-in) writing steps, unused
    podcast_folder = workspace() / podcast.FOLDER / "moon"
    first = jobs.Job(kind="podcast", slug="moon", title="Moon", topic="Moon", session_id="chat-1",
                     folder=podcast_folder)
    assert jobs.submit(first) == 1
    assert jobs.submit(topic_job()) == 2
    await jobs._queue.join()
    assert [text for text, _session, _media in chat.posts] == [
        "The podcast about Moon is ready.", "The deck about How tides work is ready."]


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

