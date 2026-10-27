"""An audio story from the user's own pages: photos of a book's pages read into one text (read_pages, each photo by
the chat model), and the story made from that text (make_audio_story(source=…), the writer's adaptation mode and its
check that the script keeps the pages). The model that reads a photo is a fake here; it was checked live on 27 Oct
(odie.making.pages says what was measured)."""
import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from odie import voice
from odie.making import pages, story_writer
from odie.skills.registry import _load_tools
from odie.store.db import Store
from tests.test_story_writer import Turn

SKILL = Path(voice.__file__).parent / "skills" / "audio-story"


def photo_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1200), (250, 250, 245)).save(buffer, "PNG")
    return buffer.getvalue()


# Reading the pages.

def test_the_photos_are_named_by_their_ids(isolated_settings, tmp_path):
    from odie.app.images import prepare_image
    one = "a" * 32
    assert pages.sources_as_given([one, "b" * 32]) == [one, "b" * 32]
    assert pages.sources_as_given(f'["{one}"]') == [one]
    with pytest.raises(pages.PagesProblem):
        pages.sources_as_given(None)
    photo = prepare_image(photo_bytes(), tmp_path)
    page = pages.page_of(photo["id"], 2, tmp_path)
    assert page.label == "photo 2" and page.kept == tmp_path / f"{photo['id']}.txt"
    with pytest.raises(pages.PagesProblem, match="no photo with the id"):
        pages.page_of("c" * 32, 1, tmp_path)
    with pytest.raises(pages.PagesProblem, match="isn't an upload id"):
        pages.page_of("../etc", 1, tmp_path)


async def test_a_photo_is_read_once_by_the_model_and_kept(tmp_path):
    asked = []

    async def reader(image):
        asked.append(image)
        return "The ferry ran twice a day."

    page = pages.Page(label="photo 1", image=b"jpeg", kept=tmp_path / "p.txt")
    assert await pages.read_one(page, reader) == "The ferry ran twice a day."
    assert await pages.read_one(page, reader) == "The ferry ran twice a day."
    assert len(asked) == 1  # the second time from what was kept


async def test_a_model_that_cant_see_pictures_is_said_plainly(tmp_path):
    async def refuses(image):
        raise RuntimeError('litellm.BadRequestError: OpenAIException - model does not support image input')

    async def says_so(image):
        return "I'm sorry, I can't see images."

    async def says_nothing(image):
        return "  "

    page = pages.Page(label="photo 2", image=b"jpeg", kept=tmp_path / "p.txt")
    for reader in (refuses, says_so):
        with pytest.raises(pages.PagesProblem) as e:
            await pages.read_one(page, reader)
        assert str(e.value) == "Your chat model can't read photos. Choose a model that can see images."
    with pytest.raises(pages.PagesProblem, match="Photo 2 came back empty"):
        await pages.read_one(page, says_nothing)
    assert not page.kept.exists()  # nothing kept from a failed reading


async def test_reading_stops_once_the_pages_run_past_what_a_story_takes(tmp_path):
    asked = []

    async def reader(image):
        asked.append(image)
        return "word " * 300

    many = [pages.Page(label=f"photo {n}", image=bytes([n]), kept=tmp_path / f"{n}.txt") for n in range(1, 11)]
    reading = await pages.read(many, reader, 700)
    assert reading.past_the_limit and len(asked) == 4  # the first four, read together; the rest never
    assert pages.pages_that_fit(reading.texts, 700) == 2
    whole = await pages.read([pages.Page("photo 1", b"x", tmp_path / "x.txt")], reader, 700)
    assert not whole.past_the_limit and len(whole.texts) == 1


def test_the_model_is_asked_with_the_page_inline(monkeypatch):
    seen = {}

    async def fake_completion(store, slot, messages, thinking=False, **opts):
        seen.update(slot=slot, messages=messages, opts=opts)
        return "words"

    import odie.models
    monkeypatch.setattr(odie.models, "chat_completion", fake_completion)
    assert asyncio.run(pages.model_reads("store", b"\xff\xd8jpeg")) == "words"
    [message] = seen["messages"]
    text, picture = message["content"]
    assert text == {"type": "text", "text": pages.TRANSCRIBE}
    assert picture["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert seen["slot"] == "chat" and seen["opts"] == {"temperature": 0}


# The tools.

def tools() -> dict:
    return {t.name: t for t in _load_tools(SKILL, "audio-story")}


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    from odie.making import jobs
    jobs.hooks["store"] = s
    s.set_setting("voice", {"engine": "kokoro"})
    monkeypatch.setenv("ODIE_VOICE", "on")
    return s


@pytest.fixture
def reads(monkeypatch):
    """The chat model's reading of a photo, faked: each photo reads as the next text in the list."""
    said = []

    async def fake(store, image):
        return said.pop(0)

    monkeypatch.setattr(pages, "model_reads", fake)
    return said


async def read_pages(sources) -> dict:
    from google.adk.tools import FunctionTool
    return await FunctionTool(tools()["read_pages"].func).run_async(args={"sources": sources}, tool_context=None)


async def test_photos_are_read_into_one_source(store, reads):
    from odie.agent.tools.files import workspace
    from odie.app.images import prepare_image, uploads_dir
    ids = [prepare_image(photo_bytes(), uploads_dir())["id"] for _ in range(2)]
    reads.extend(["The ferry from Kettle Island ran twice a day.", "Mara lowered her mug. \"Is that the ferry?\""])
    out = await read_pages(ids)
    assert out["pages"] == 2 and out["source"].startswith("pages-")
    assert out["text"] == ("The ferry from Kettle Island ran twice a day.\n\nMara lowered her mug. \"Is that the "
                           "ferry?\"")
    assert out["words"] == len(out["text"].split()) and out["minutes"] == 1
    kept = workspace() / "stories" / f"{out['source']}.txt"
    assert kept.read_text() == out["text"]
    assert str(kept).startswith(str(store.path.parent))  # the test's own folder, never ~/.odie


async def test_pages_past_fifteen_minutes_ask_which_to_make(store, reads, monkeypatch):
    from odie.app.images import prepare_image, uploads_dir
    ids = [prepare_image(photo_bytes(), uploads_dir())["id"] for _ in range(6)]
    reads.extend(["word " * 600] * 6)
    out = await read_pages(ids)
    assert out == {"too_long": "These pages run past 15 minutes, the longest an audio story can be. The first 3 "
                               "(photo 1 to photo 3) make about 14 minutes. Ask the user which pages to make, then "
                               "call read_pages again with just those."}
    assert len(reads) == 2  # the last two photos were never read


async def test_a_bad_source_says_what_to_send(store, reads):
    assert "upload ids" in (await read_pages(["not-an-id"]))["error"]


def test_the_most_a_story_takes_follows_the_voices_pace():
    most = tools()["read_pages"].func.__globals__["most_words"]
    minutes_for = tools()["read_pages"].func.__globals__["minutes_for"]
    assert most("phonon") == 2522 and most("kokoro") == 1977
    assert minutes_for(924, 185) == 6 and minutes_for(100, 185) == 1


CAST = [{"id": "narrator", "name": "Narrator", "voice": "bf_emma", "about": "an outside storyteller", "gender": "any"},
        {"id": "tobias", "name": "Tobias", "voice": "bm_george", "about": "the old harbour master", "gender": "male"}]


@pytest.fixture
def queued(store, monkeypatch, tmp_path):
    from odie.making import jobs, sound_library
    monkeypatch.setattr(sound_library, "LIBRARY_ROOT", tmp_path / "no-imovie")
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return submitted


async def make(**args) -> dict:
    from google.adk.tools import FunctionTool
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    return await FunctionTool(tools()["make_audio_story"].func).run_async(args=args, tool_context=chat)


async def test_a_story_from_pages_needs_no_genre_or_length(queued, reads):
    from odie.app.images import prepare_image, uploads_dir
    photo = prepare_image(photo_bytes(), uploads_dir())
    reads.append("\"Go back to the house, Elsie,\" Tobias said quietly.")
    read = await read_pages([photo["id"]])
    out = await make(title="The Bell at Kettle Island", cast=CAST, narrator="narrator", accent="British",
                     source=read["source"], minutes=99)  # a length the user never chose is not used
    assert "result" in out
    [job] = queued
    request = job.data["request"]
    assert request.source == read["text"] and request.genre == "" and request.minutes == 1
    assert request.premise == "The Bell at Kettle Island"  # the title says what the passage is
    assert f"From the user's pages: {read['source']}" in job.brief
    missing = await make(title="T", cast=CAST, narrator="narrator", source="pages-0000000000")
    assert missing["error"].startswith('There are no pages read as "pages-0000000000"')
    assert (await make(title="T", cast=CAST, narrator="narrator"))["error"].startswith("genre is")


async def test_the_voices_are_asked_before_the_story_is_made(queued, reads):
    """On 27 Oct DeepSeek read the pages and made the story in the same turn, choosing the voices itself."""
    from odie.agent import turn
    from odie.app.images import prepare_image, uploads_dir
    photo = prepare_image(photo_bytes(), uploads_dir())
    reads.append("\"Go back to the house, Elsie,\" Tobias said quietly.")
    token = turn.USER_TEXT.set("Make an audio drama of these pages")
    try:
        read = await read_pages([photo["id"]])
        same_turn = await make(title="T", cast=CAST, narrator="narrator", source=read["source"])
        assert same_turn["error"].startswith("The user hasn't chosen the voices yet: ask the one form first")
        assert queued == []
        turn.USER_TEXT.set("Accent: British. Narrator: Fable…")  # the form's answer, the next turn
        assert "result" in await make(title="T", cast=CAST, narrator="narrator", source=read["source"])
    finally:
        turn.USER_TEXT.reset(token)


def test_the_skill_reads_pages_before_one_form():
    text = (SKILL / "SKILL.md").read_text()
    assert "adk_additional_tools: [story_voices, read_pages, make_audio_story]" in text
    section = text[text.index("## From the user's pages"):]
    assert "read_pages" in section and "make_audio_story(source=" in section and "too_long" in section
    assert "No\n   genre, story or length questions" in section


# The writer's adaptation mode.

SOURCE = ("The bell rang again. \"Go back to the house, Elsie,\" Tobias said quietly. \"But it is, isn't it?\" "
          "The girl did not move.")
CATALOGUE = [{"id": "ambience/harbour", "kind": "loop"}, {"id": "foley/bell", "kind": "hit"}]


def adapted(lines: list[dict]) -> dict:
    return {"title": "The Bell", "scenes": [{"title": "Prelude", "bed": {"sound": "ambience/harbour"},
                                             "lines": [{"sound": "foley/bell", "lead": 3}, *lines]}]}


ELSIE_CAST = [*CAST, {"id": "elsie", "name": "Elsie", "voice": "bf_alice", "gender": "female"}]


def test_an_adaptation_may_open_on_a_characters_line_after_the_sound():
    script = adapted([{"speaker": "tobias", "text": "Go back to the house, Elsie."}])
    assert story_writer.script_problems(script, CATALOGUE, ELSIE_CAST, adapting=True) == []
    refused = story_writer.script_problems(script, CATALOGUE, ELSIE_CAST)
    assert refused and "the narrator speaks first" in refused[0]


def test_an_adaptation_keeps_most_of_the_pages_and_adds_nothing():
    kept = story_writer.parse_script(adapted([
        {"speaker": "narrator", "text": "The bell rang again."},
        {"speaker": "tobias", "text": "Go back to the house, Elsie."},
        {"speaker": "elsie", "text": "But it is, isn't it?"},
        {"speaker": "narrator", "text": "The girl did not move."}]))
    words = len(SOURCE.split())
    assert story_writer.kept_problem(kept, words) is None  # 20 of 23: only the tag "Tobias said quietly" went
    summed_up = story_writer.parse_script(adapted([{"speaker": "narrator", "text": "Elsie stayed."}]))
    assert story_writer.kept_problem(summed_up, words) == (
        "The script keeps about 2 of the pages' 23 words (9%); keep at least 75%. Put back the narration and dialogue "
        "you left out, in the author's words: drop only the tags that say who speaks (\"he said\") and what works only "
        "in print.")
    padded = story_writer.parse_script(adapted([{"speaker": "narrator", "text": SOURCE + " " + SOURCE}]))
    assert "adds lines the pages don't have" in story_writer.kept_problem(padded, words)


def test_the_adaptation_prompt_carries_the_whole_text_last():
    request = story_writer.Request(genre="", premise="The bell at the pier", cast=ELSIE_CAST, narrator="narrator",
                                   accent="British", minutes=1, source=SOURCE)
    prompt = story_writer.prompt_for(request, "ambience/harbour · 30s · loop")
    assert prompt.startswith("Adapt the user's pages below into the audio story")
    assert "Genre: (as the text reads)" in prompt and "The passage: The bell at the pier" in prompt
    assert "Length: the text's own, 23 words" in prompt and "keep at least 75% of its words" in prompt
    assert prompt.index("Sounds (use these ids exactly)") < prompt.index("The source text") < prompt.index(SOURCE)
    assert "## When the story comes from the user's pages" in story_writer.INSTRUCTION
    invented = story_writer.Request(genre="mystery", premise="p", cast=CAST, narrator="narrator", accent="British",
                                    minutes=2)
    assert "source text" not in story_writer.prompt_for(invented, "listing")


async def test_a_summary_is_sent_back_once_then_let_through_with_a_note():
    request = story_writer.Request(genre="", premise="The bell", cast=ELSIE_CAST, narrator="narrator",
                                   accent="British", minutes=1, source=SOURCE)
    summed_up = adapted([{"speaker": "narrator", "text": "Elsie stayed."}])

    async def script(turn):
        await turn.submit(summed_up)
        await turn.submit(summed_up)

    turn = Turn(script)  # the story writer's tests' stand-in for the focused turn
    written = await story_writer.write(request, CATALOGUE, "listing", turn)
    assert turn.said[0]["error"].startswith("The script keeps about 2 of the pages' 23 words")
    assert turn.said[1] == {"result": "Accepted."}
    assert written.note == "The script kept about 2 of the pages' 23 words (asked once to keep to them)."
