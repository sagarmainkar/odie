"""make_video, the explainer-video skill's chat tool: the chat only briefs the video. What it refuses (in the order the
spec gives), the job it queues (a topic, a length and a brief; the writer writes the page later, in the job), a folder
of its own for every video, and the reply that says how long."""
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk.tools import FunctionTool
from PIL import Image

from odie import browser as odie_browser
from odie import voice
from odie.browser import RENDER_ARGS, find
from odie.making import chat as making_chat
from odie.making import jobs
from odie.store.db import Store
from odie.video import kind, page

SKILL = Path(page.__file__).parent.parent / "skills" / "explainer-video"
GOLDEN = Path(__file__).parent / "golden" / "tool_declarations.json"


def load_tools():
    spec = importlib.util.spec_from_file_location("explainer_video_tools", SKILL / "tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tools = load_tools()


LIBRARY_UUID = "3F2A"  # the user's own picture the examples below use, with a full copy on this Mac


def a_copy(path: Path, width: int, height: int) -> str:
    """A JPEG of that size at path, standing for a copy Photos keeps on this Mac."""
    Image.new("RGB", (width, height), (30, 90, 60)).save(path, "JPEG")
    return str(path)


def put_in_library(store, tmp_path: Path, small: dict[str, int] | None = None, full: tuple[str, ...] = ()) -> None:
    """The real index's photos: LIBRARY_UUID and each uuid in `full` with a 2048×1536 copy, and each uuid in `small`
    with only a copy of that many pixels on its long side."""
    from odie.photos.library import PhotoRow
    from odie.vault import settings as vault_settings
    copies = {LIBRARY_UUID: a_copy(tmp_path / "full.jpeg", 2048, 1536)}
    for uuid in full:
        copies[uuid] = a_copy(tmp_path / f"{uuid}.jpeg", 2048, 1536)
    for uuid, side in (small or {}).items():
        copies[uuid] = a_copy(tmp_path / f"{uuid}.jpeg", side, side * 3 // 4)
    rows = [PhotoRow(uuid=uuid, kind="photo", taken="2026-05-12T10:00:00", people=[], labels=[], place="Nathula",
                     city="", country="India", albums=[], big=big) for uuid, big in copies.items()]
    vault_settings.index_for(store).index_photos(rows)


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A browser said to be present, a store for the voice and for the user's photos (LIBRARY_UUID in the real index,
    with a full copy), and jobs.submit replaced by a recorder. Everything on disk is under tmp_path."""
    from odie.photos import settings as photo_settings
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    photo_settings.put(store, on=True)
    put_in_library(store, tmp_path)
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Some Browser")
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return store, submitted


# The refusals, in order: each one comes back before anything is queued.

async def test_no_browser_is_said_first_even_with_other_problems(world, monkeypatch):
    monkeypatch.setattr(find, "browser_binary", lambda: None)
    out = await tools.make_video("", minutes=9, brief="x" * 7000, voice_name="nobody")
    assert "needs Chrome, Edge, Brave or Chromium" in out["error"] and world[1] == []


async def test_an_empty_topic_is_refused(world):
    out = await tools.make_video("   ", minutes=9)
    assert "topic" in out["error"] and world[1] == []


@pytest.mark.parametrize("minutes", [0, 7, -1])
async def test_minutes_outside_one_to_six_are_refused_with_the_range(world, minutes):
    out = await tools.make_video("Attention", minutes=minutes)
    assert "from 1 to 6" in out["error"] and str(minutes) in out["error"] and world[1] == []


async def test_minutes_that_arent_a_whole_number_are_refused(world):
    out = await tools.make_video("Attention", minutes=2.5)
    assert "from 1 to 6" in out["error"] and world[1] == []


async def call_as_adk_does(**args) -> dict:
    """make_video called the way ADK calls it: through its FunctionTool, with the model's arguments as they came."""
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    return await FunctionTool(tools.make_video).run_async(args=args, tool_context=chat)


@pytest.mark.parametrize("minutes", [2.0, "2", " 2 "])
async def test_minutes_as_a_whole_float_or_text_are_read_as_the_number(world, minutes):
    out = await call_as_adk_does(topic="Attention", minutes=minutes)
    assert "result" in out, out
    assert world[1][0].minutes == 2 and type(world[1][0].minutes) is int


@pytest.mark.parametrize("minutes", ["two", "2.5", "²"])  # "²" is a digit to Python, but no number
async def test_minutes_as_text_that_isnt_a_whole_number_are_refused_naming_the_text(world, minutes):
    out = await call_as_adk_does(topic="Attention", minutes=minutes)
    assert "from 1 to 6" in out["error"] and f"got the text '{minutes}'" in out["error"] and world[1] == []


async def test_text_minutes_outside_the_range_are_refused_with_the_number(world):
    out = await call_as_adk_does(topic="Attention", minutes="9")
    assert "from 1 to 6" in out["error"] and "not 9" in out["error"] and world[1] == []


async def test_null_brief_voice_and_minutes_are_read_as_not_given(world):
    out = await call_as_adk_does(topic="Attention", minutes=None, brief=None, voice_name=None)
    assert "result" in out, out
    job = world[1][0]
    assert (job.minutes, job.brief, job.voice_name) == (2, "", "")


async def test_a_null_topic_is_the_topic_refusal(world):
    out = await call_as_adk_does(topic=None)
    assert out["error"] == tools.NO_TOPIC and world[1] == []


async def test_a_brief_over_20000_characters_is_refused(world):
    out = await tools.make_video("Attention", brief="x" * 20_001, voice_name="nobody")
    assert "20,001" in out["error"] and "20,000" in out["error"] and world[1] == []
    assert "result" in await tools.make_video("Attention", brief="x" * 20_000)


# Sources: what the user gave, read by Odie's code and put after the brief, word for word.

TIDES = "Asha's notes on tides.\n\n| place | high tide |\n|---|---|\n| Goa | 2.1 m |"


async def test_sources_go_into_the_jobs_brief_after_the_plan(world):
    from odie.agent import turn
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    token = turn.USER_TEXT.set(TIDES)  # the runner sets the user's words for the turn's tools
    try:
        out = await tools.make_video("How tides work", brief="For a ten-year-old. Show the table.",
                                     sources=["my message"], tool_context=chat)
    finally:
        turn.USER_TEXT.reset(token)
    assert "result" in out, out
    brief = submitted[0].brief
    assert brief.startswith("For a ten-year-old. Show the table.")
    assert "## Source material" in brief and TIDES in brief and "[context:" not in brief


async def test_a_source_that_cant_be_read_is_an_error_and_nothing_is_queued(world):
    out = await tools.make_video("How tides work", brief="For a ten-year-old.", sources=["../../outside.txt"])
    assert "workspace" in out["error"] and world[1] == []
    out = await tools.make_video("How tides work", sources=["a.txt"] * 6)
    assert "at most 5" in out["error"] and world[1] == []
    from odie.agent.tools.files import workspace
    videos = workspace() / "videos"
    assert not videos.exists() or not any(videos.iterdir())  # no folder made for a refused video


@pytest.mark.parametrize("given", [None, []])
async def test_no_sources_leaves_the_brief_as_it_is(world, given):
    out = await call_as_adk_does(topic="Attention", brief="For Asha.", sources=given)
    assert "result" in out, out
    assert world[1][0].brief == "For Asha."


async def test_sources_sent_as_json_text_are_read_as_the_list(world):
    out = await call_as_adk_does(topic="How tides work", brief="For Asha.", sources='["my message"]')
    assert "error" in out and "user's message" in out["error"]  # read as the list: no user turn here, so refused


async def test_sources_that_arent_a_list_are_an_error(world):
    out = await call_as_adk_does(topic="How tides work", sources={"note": "Tides"})
    assert "list" in out["error"] and world[1] == []


async def test_a_voice_from_the_other_engine_is_refused_and_nothing_is_queued(world):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("Attention", voice_name="cedar")
    assert "cedar" in out["error"] and "Settings" in out["error"] and submitted == []


async def test_a_voice_of_the_chosen_engine_goes_to_the_job_by_its_id(world):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("Attention", voice_name="Michael")
    assert "result" in out and submitted[0].voice_name == "am_michael"


# A good call: the job carries what the writer needs, and no page.

async def test_a_good_call_queues_a_job_with_the_topic_minutes_and_brief(world, tmp_path):
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    brief = "For Asha, a beginner. 1. Words become vectors. 2. Each word asks every other word how much to listen."
    out = await tools.make_video(" How attention works ", minutes=3, brief=brief, tool_context=chat)
    assert "result" in out, out
    job = submitted[0]
    assert (job.topic, job.title, job.minutes, job.brief) == ("How attention works", "How attention works", 3, brief)
    assert job.kind == "video" and job.voice_name == ""
    assert job.data == {"given": {"images": [], "clips": []}, "private": [], "sounds": True, "style": "",
                        "aspect": "landscape"}  # no page yet
    assert job.slug == "how-attention-works" and job.session_id == "chat-7"
    assert job.folder.is_dir() and str(job.folder).startswith(str(tmp_path))
    assert kind.needs_writing(job)


async def test_the_length_defaults_to_two_minutes(world):
    await tools.make_video("Attention")
    assert world[1][0].minutes == 2


async def test_the_same_topic_twice_gets_two_folders(world):
    _store, submitted = world
    await tools.make_video("How Attention Works!")
    await tools.make_video("How Attention Works!")
    first, second = submitted
    assert first.folder.name == "how-attention-works" and second.folder.name == "how-attention-works-2"
    assert first.folder.parent == second.folder.parent and first.folder.parent.name == "videos"
    assert second.slug == "how-attention-works-2"


def test_the_slug_is_plain_lower_case_with_hyphens():
    assert making_chat.slug_of("Speculative decoding", "video") == "speculative-decoding"
    assert making_chat.slug_of("TCP/IP, explained", "video") == "tcp-ip-explained"
    assert making_chat.slug_of("¿Qué?", "video") == "qu"
    assert making_chat.slug_of("!!!", tools.WORD) == "video"


# The estimate and the reply.

def test_the_making_counts_narrating_rendering_and_joining_in_seconds():
    # the first live run: 6 scenes, 96.25 s of speech, a 98.75 s video of 2,963 frames, made in well under a minute
    assert round(tools.making_seconds(96.25, 2963), 1) == 62.0  # 9.6 narrating + 42.3 drawing + 10 joining


def test_writing_takes_a_minute_per_minute_of_video_and_at_least_two():
    # live: a 2-minute video ~1.5 min of writing; a 4-minute one with a long source ~5.5 min
    assert [tools.writing_minutes(m) for m in (1, 2, 4, 6)] == [2, 2, 4, 6]


def test_the_estimate_adds_the_writing_to_the_making():
    # 2 minutes: 120 s of speech in 6 scenes, 122.5 s of video, 3,675 frames -> 12 + 52.5 + 10 = 74.5 s -> 1, + 2
    assert tools.minutes_to_make(2) == 3
    assert tools.minutes_to_make(1) == 3  # 42.1 s of making -> at least 1, + 2
    assert tools.minutes_to_make(4) == 6  # 139.2 s -> 2, + 4
    assert tools.minutes_to_make(6) == 9  # 203.9 s -> 3, + 6


def test_fetching_takes_about_a_second_a_picture_and_five_a_clip():
    assert tools.gathering_seconds(0, 0) == 0
    assert tools.gathering_seconds(12, 3) == 27  # 12 + 15
    assert tools.gathering_seconds(20, 6) == 50


def test_the_estimate_adds_the_pictures_and_clips_to_the_making():
    # 2 minutes: 74.5 s of making; 6 pictures -> 80.5 s, still 1 minute -> 3; 20 pictures and 6 clips -> 124.5 s -> 4
    assert tools.minutes_to_make(2, images=6) == 3
    assert tools.minutes_to_make(2, images=20, clips=6) == 4
    assert tools.minutes_to_make(2, images=0, clips=0) == tools.minutes_to_make(2)


async def test_the_reply_counts_the_pictures_and_clips(world):
    images = [f"https://ex.com/{i}.jpg — picture {i} (Photo by A on Unsplash)" for i in range(20)]
    clips = [f"https://ex.com/{i}.mp4 — clip {i} (Pexels, by B)" for i in range(6)]
    out = await tools.make_video("Goa", minutes=2, images=images, clips=clips)
    assert out["result"].startswith("Making it now: about 4–6 minutes")


async def test_the_reply_says_how_long_and_that_the_chat_stays_free(world, monkeypatch):
    out = await tools.make_video("Attention", minutes=2)
    assert out["result"].startswith("Making it now: about 3–5 minutes (writing the script and the animation, then "
                                    "drawing it). It'll appear in this chat, with a ping on the phone")
    assert "keep chatting" in out["result"]

    monkeypatch.setattr(jobs, "submit", lambda job: 2)
    queued = await tools.make_video("Attention", minutes=2)
    assert queued["result"].startswith("It's number 2 in line, about 3–5 minutes after the one before. It'll appear")
    assert re.search(r"about \d+–\d+ minutes", queued["result"]) and "keep chatting" in queued["result"]


# What the chat model is offered.

def test_the_skill_offers_only_make_video_without_an_approval_card(isolated_settings, tmp_path):
    from odie.skills.registry import discover
    store = Store(tmp_path / "skills.db")
    store.init_schema()
    entry = {e.name: e for e in discover(store, user_dir=tmp_path / "none")}["explainer-video"]
    assert entry.status == "ok" and entry.tools == ["make_video"]
    assert entry.skill.frontmatter.metadata["title"] == "Explainer videos"
    assert not any(tool._require_confirmation for tool in entry.tool_objs)


def test_the_declaration_has_exactly_its_parameters_with_the_dialogue_ones_last():
    declaration = FunctionTool(tools.make_video)._get_declaration()
    properties = declaration.parameters_json_schema["properties"]
    assert list(properties) == ["topic", "minutes", "brief", "sources", "images", "clips", "sounds", "voice_name", "style",
                                "aspect", "timed_segment_seconds", "brand_kit", "script", "voices"]
    assert properties["sounds"] == {"default": True, "title": "Sounds", "type": "boolean"}
    assert "sounds: leave true; false only when the user asks for no sound effects" in declaration.description
    for name in ("sources", "images", "clips"):
        assert properties[name]["anyOf"][0] == {"items": {"type": "string"}, "type": "array"}  # a list of texts
    assert "address — what it shows" in declaration.description and "at most 20" in declaration.description
    assert declaration.parameters_json_schema["required"] == ["topic"]

    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    assert sorted(golden["make_video"]["parameters_json_schema"]["properties"]) == sorted(properties)
    assert "save_video_page" not in golden and "submit_video" not in golden  # the writer's tools, never the chat's


def test_the_skill_says_how_to_write_the_brief():
    text = (SKILL / "SKILL.md").read_text()
    assert "brief" in text and "can't see" in text and "20,000" in text
    assert "sources" in text and "my message" in text and "earlier message" in text
    assert "no emojis" in text and "save_video_page" not in text
    assert len(text.split("---", 2)[2].split()) < 900  # short: the writer has the page contract and the film grammar


def test_the_skill_says_sounds_are_on_unless_the_user_says_no_sound_effects():
    text = (SKILL / "SKILL.md").read_text()
    assert "sounds=false" in text and "no sound effects" in text


def test_the_skill_says_how_to_gather_pictures_clips_and_places():
    text = (SKILL / "SKILL.md").read_text()
    assert "find_images" in text and "find_clips" in text and 'search_everything(only="photos"' in text
    assert "photo:<id>" in text and "upload:<id>" in text and "screenshot:<id>" in text
    assert "6–20" in text and "0–6" in text  # pictures and clips: the ranges that work
    assert "lat, lon" in text and "Gangtok" in text and "Lachung" in text  # a town the map may not know
    assert "private chat" in text and "open it in Photos once" in text
    assert "Unsplash, Pexels" in text and "watermarked" in text  # free pictures first; never a stock site's preview


def test_the_skill_says_videos_can_be_3d_with_real_surfaces():
    """Chat once told the user make_video can't use pictures in 3D: it can (s.texture), and a planet's flat texture
    map wraps on a sphere. The skill says so, so chat offers it."""
    text = (SKILL / "SKILL.md").read_text()
    assert "3D" in text and "texture map" in text
    guide = (Path(page.__file__).parent / "writer.md").read_text()
    assert "SphereGeometry" in guide and "texture map" in guide


def test_videos_are_drawn_in_a_browser_cut_off_from_the_network(isolated_settings, monkeypatch):
    monkeypatch.setattr(odie_browser, "_render", None)
    browser = odie_browser.render_browser()  # made, not started
    assert browser.extra_args == RENDER_ARGS
    assert "--proxy-server=socks5://127.0.0.1:9" in browser.extra_args
    assert str(browser.profile).startswith(str(isolated_settings.data_dir))


# Pictures and clips: lines of "address — words", checked here, fetched later by the job.

PICTURES = ["https://images.unsplash.com/a.jpg — Red Fort, Delhi, at dusk (Photo by A on Unsplash)",
            "photo:3F2A — Nathula pass, us at the gate, 12 May 2026"]
CLIPS = ["https://videos.pexels.com/v.mp4 — waves on a Goa beach, slow (Pexels, by B)"]


async def test_pictures_and_clips_go_to_the_job_as_given_and_stay_out_of_the_writers_brief(world):
    _store, submitted = world
    out = await tools.make_video("Goa", brief="For Asha.", images=[f"  {PICTURES[0]} ", PICTURES[1]], clips=CLIPS)
    assert "result" in out, out
    job = submitted[0]
    assert job.data["given"] == {"images": PICTURES, "clips": CLIPS}
    assert job.brief == "For Asha."  # the writer reads names and words (the listing), never the addresses


async def test_pictures_sent_as_json_text_are_read_as_the_list(world):
    out = await call_as_adk_does(topic="Goa", images=json.dumps(PICTURES), clips=None)
    assert "result" in out, out
    assert world[1][0].data["given"] == {"images": PICTURES, "clips": []}


@pytest.mark.parametrize(("images", "clips", "words"), [
    ({"a": "b"}, None, "images is a list of short texts"),
    (["https://ex.com/a.jpg - Akbar"], None, "images line 1 has no"),
    (None, ["photo:3F2A — us"], "a clip is a web address"),
    ([f"photo:{i} — picture {i}" for i in range(21)], None, "at most 20"),
    (None, [f"https://ex.com/{i}.mp4 — clip {i}" for i in range(7)], "at most 6"),
])
async def test_pictures_that_cant_be_read_are_refused_and_nothing_is_queued(world, images, clips, words):
    out = await call_as_adk_does(topic="Goa", images=images, clips=clips)
    assert words in out["error"] and world[1] == []
    from odie.agent.tools.files import workspace
    videos = workspace() / "videos"
    assert not videos.exists() or not any(videos.iterdir())  # no folder made for a refused video


async def test_the_chats_private_sites_go_with_the_job(world):
    from odie.agent import turn
    _store, submitted = world
    token = turn.PRIVATE.set({"swiggy.com", "amazon.in"})
    try:
        out = await tools.make_video("Goa", images=PICTURES)
    finally:
        turn.PRIVATE.reset(token)
    assert "result" in out, out
    assert submitted[0].data["private"] == ["amazon.in", "swiggy.com"]


async def test_a_library_picture_with_only_a_small_copy_is_left_out_and_the_chat_is_told(world, tmp_path):
    store, submitted = world
    put_in_library(store, tmp_path, small={"5A11": 360})
    lake = "photo:5A11 — Asha at Tsomgo lake, ice at the edge, 11 May 2026"
    out = await tools.make_video("Sikkim", images=[PICTURES[1], lake, PICTURES[0]])
    assert "result" in out, out
    assert submitted[0].data["given"]["images"] == [PICTURES[1], PICTURES[0]]  # the video goes on without it
    assert out["result"].startswith("Making it now: about")
    assert ("Left out: Asha at Tsomgo lake, ice at the edge, 11 May 2026 (photo:5A11 has only a small copy on this "
            "Mac (360 px); open it in Photos once so the full picture comes down).") in out["result"]
    assert out["result"].endswith("Add that to the reply in a few words, with what the user can do; the video goes on "
                                  "without them.")


async def test_a_library_picture_that_isnt_there_is_left_out_with_why(world):
    _store, submitted = world
    out = await tools.make_video("Sikkim", images=["photo:NOPE — us at the gate"])
    assert submitted[0].data["given"]["images"] == []
    assert "There's no picture photo:NOPE in the user's Photos library here." in out["result"]


async def test_web_pictures_and_full_library_copies_leave_the_reply_as_it_was(world):
    out = await tools.make_video("Goa", images=PICTURES)
    assert "Left out" not in out["result"]
    assert world[1][0].data["given"]["images"] == PICTURES


async def test_words_after_a_library_id_in_a_line_keep_the_picture(world, tmp_path):
    from odie.decks import photos
    from odie.video import assets
    store, submitted = world
    uuid = "0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF"
    put_in_library(store, tmp_path, full=(uuid,))
    line = f"photo:{uuid} (for a video or a deck) — us at Nathula, prayer flags in the snow"
    out = await tools.make_video("Sikkim", images=[line])
    assert "Left out" not in out["result"]
    assert submitted[0].data["given"]["images"] == [line]
    pictures, _ = assets.parse(submitted[0].data["given"]["images"], None)
    got = await photos.fetch(pictures[0].address)  # what the job does with the line
    assert got.ref == f"photo:{uuid}" and (got.width, got.height) == (2000, 1500)


async def test_in_a_private_chat_web_pictures_and_clips_are_left_out_and_the_chat_is_told(world):
    from odie.agent import turn
    _store, submitted = world
    fort = "https://images.unsplash.com/a.jpg — Red Fort, Delhi, at dusk (Photo by A on Unsplash)"
    gate = "photo:3F2A — Nathula pass, us at the gate, 12 May 2026"
    waves = "https://videos.pexels.com/v.mp4 — waves on a Goa beach, slow (Pexels, by B)"
    token = turn.PRIVATE.set({"amazon.in"})
    try:
        out = await tools.make_video("Goa", images=[fort, gate], clips=[waves])
    finally:
        turn.PRIVATE.reset(token)
    assert "result" in out, out
    assert submitted[0].data["given"] == {"images": [gate], "clips": []}  # the user's own picture goes on
    reason = "not fetched: this chat read a signed-in page, so photos from the web aren't fetched here"
    assert (f"Left out: Red Fort, Delhi, at dusk ({reason}); waves on a Goa beach, slow ({reason}).") in out["result"]
    assert "Add that to the reply in a few words" in out["result"]


# Sound effects: on unless the chat turns them off for this video; the making step reads the same key.

async def test_sounds_are_on_by_default_and_the_making_step_mixes_them(world):
    _store, submitted = world
    out = await tools.make_video("Attention")
    assert "result" in out, out
    assert submitted[0].data["sounds"] is True and kind.wants_sounds(submitted[0])


async def test_no_sound_effects_reaches_the_job_and_the_making_step_mixes_none(world):
    _store, submitted = world
    out = await tools.make_video("Attention", sounds=False)
    assert "result" in out, out
    assert submitted[0].data["sounds"] is False and not kind.wants_sounds(submitted[0])


@pytest.mark.parametrize(("given", "meant"), [(None, True), (True, True), (False, False), ("false", False),
                                              (" False ", False), ("no", False), ("true", True)])
async def test_sounds_as_the_model_sends_them_are_read_as_on_or_off(world, given, meant):
    out = await call_as_adk_does(topic="Attention", sounds=given)
    assert "result" in out, out
    assert world[1][0].data["sounds"] is meant


# A dialogue video: the user's script, each speaker in their own voice (odie.video.dialogue).

NIGHT = "## Scene: A workshop at night\nNARRATOR: The lamp burned on.\nANNA: Still here? [pause 1]\nBEN: Always.\n"


def a_script(text: str = NIGHT) -> str:
    from odie.agent.tools.files import workspace
    path = workspace() / "night.md"
    path.write_text(text)
    return "night.md"


async def test_a_script_with_a_voice_for_each_speaker_queues_a_dialogue_video(world):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("The night shift", brief="Warm lamplight, two friends.", script=a_script(),
                                 voices=[{"id": "Anna", "name": "Bella"}, {"id": "ben", "name": "Michael"}])
    assert "result" in out, out
    kept = submitted[0].data["dialogue"]
    assert kept["voices"] == {"anna": "af_bella", "ben": "am_michael"}  # by speaker, as voice ids
    assert [line["speaker"] for line in kept["script"][0]["lines"]] == ["narrator", "anna", "ben"]
    assert submitted[0].brief == "Warm lamplight, two friends."  # the script isn't retyped into the brief


async def test_a_dialogue_script_is_refused_before_queueing_when_it_cant_be_staged(world):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("Night", script=a_script(), voices=[{"id": "anna", "name": "Bella"}])
    assert "ben" in out["error"] and "voice" in out["error"]
    out = await tools.make_video("Night", script=a_script("Just notes, nobody speaks."),
                                 voices=[{"id": "anna", "name": "Bella"}])
    assert "no lines" in out["error"]
    out = await tools.make_video("Night", script=a_script(), voices=[{"id": "anna", "name": "cedar"},
                                                                     {"id": "ben", "name": "Michael"}])
    assert "cedar" in out["error"]
    out = await tools.make_video("Night", script=a_script(), voices=[{"id": "anna", "name": "Bella"},
                                                                     {"id": "ben", "name": "Michael"}],
                                 timed_segment_seconds=60)
    assert "dialogue" in out["error"]
    out = await tools.make_video("Night", script="missing.md", voices=[])
    assert "error" in out
    assert submitted == []
