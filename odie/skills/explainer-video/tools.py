"""The explainer-video skill's tool: make_video checks the request within the chat turn (instantly), reads the sources
the chat named (odie.making.sources: the user's message, a note, a workspace file, word for word) and puts the video in
Odie's background queue (odie.making.jobs, kind "video" from odie.video.kind) with the brief and the sources as one
text, the job's brief.md. The pictures and clips the chat found (images, clips: "address — what it shows" lines) are
checked here and go with the job, with the chat's private sites; the job fetches them before the writer runs
(odie.video.assets). A picture from the user's library that can't go in (only a small copy on this Mac), and in a
private chat every web picture and clip, is left out here, and the result says so, so the chat can tell the user at
once. In the background the writer (odie.video.writer) turns the topic, length, that brief and the pictures' names
into the narration and the page; then the video is narrated, rendered and posted to this chat. The chat only briefs
the video. Plain trusted code of a built-in skill: no shell, no approval card."""
import asyncio
import json

from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import workspace
from odie.agent.turn import private_sites
from odie.browser import find
from odie.decks import photos
from odie.making import chat, jobs
from odie.making import sources as making_sources
from odie.video import assets, brand, dialogue, kind, timed, timeline

NARRATING_SPEED = 10  # seconds of speech the voice narrates in a second
JOINING_SECONDS = 10  # joining the segments and the sound into the MP4
MIN_WRITING_MINUTES = 2  # the writer's turn, at least (live: about 100 s for a 7-scene page, from a ~4.7k-token prompt)
SCENE_SECONDS = 20  # a scene lasts about this long, for counting the breaths between scenes before there are any
ESTIMATE_SPREAD = 2  # the range told is N to N + 2 minutes: writing time varies the most
SECONDS_A_PICTURE = 1  # fetching and preparing one picture before the writer starts
SECONDS_A_CLIP = 5  # downloading one clip and re-encoding its first 15 s (about 3 s measured, for 1080p)
MIN_MINUTES = 1
DEFAULT_MINUTES = 2
MAX_BRIEF_CHARACTERS = 20_000  # the chat model's own brief; the sources have their own limits (odie.making.sources)
MAX_STYLE_CHARACTERS = 300  # a narration style is one line; anything longer is cut, not refused
WORD = "video"
DOING = "writing the script and the animation, then drawing it"  # the middle of the reply: what making it involves

NO_BROWSER = ("An explainer video needs Chrome, Edge, Brave or Chromium on this computer to draw its frames, and none "
              "was found. Tell the user to install one (any of them) and ask again.")
NO_TOPIC = 'Give the topic: a few words saying what the video is about, like "How attention works".'
LEFT_OUT = ("Left out: {pictures}. Add that to the reply in a few words, with what the user can do; the video goes "
            "on without them.")
SOUNDS_OFF = ("false", "no", "off", "0")  # sounds sent as text that turn them off, after strip and lower case
# The words for a 9:16 reel, after strip and lower case; any other word ("landscape", "wide", "16:9", "") is landscape.
VERTICAL_WORDS = ("vertical", "portrait", "reel", "insta", "shorts", "9:16")


def making_seconds(speech_seconds: float, frames: int) -> float:
    """How long making a video takes, in seconds: narrating its speech (10 seconds of speech a second), drawing its
    frames (timeline.RENDER_RATE a second) and joining them (10 s). The first live run, 96.25 s of speech in a 98.75 s
    video of 2,963 frames -> 9.6 + 42.3 + 10 = 62 s."""
    narrating = speech_seconds / NARRATING_SPEED
    drawing = frames / timeline.RENDER_RATE
    return narrating + drawing + JOINING_SECONDS


def writing_minutes(minutes: int) -> int:
    """How long the writer's turn takes, in whole minutes: about a minute per minute of video, at least 2. Live: a
    2-minute video took ~1.5 minutes -> 2; a 4-minute one with a 9,400-character source took ~5.5 -> 4 (the estimate
    told is a range of 4 + making to 2 more); 6 -> 6."""
    return max(MIN_WRITING_MINUTES, minutes)


def gathering_seconds(images: int, clips: int) -> int:
    """How long fetching and preparing the pictures and clips adds, in seconds: about a second a picture and five a
    clip. 12 pictures and 3 clips -> 12 + 15 = 27 s; 20 and 6 -> 50 s; none -> 0."""
    pictures = images * SECONDS_A_PICTURE
    moving = clips * SECONDS_A_CLIP
    return pictures + moving


def minutes_to_make(minutes: int, images: int = 0, clips: int = 0) -> int:
    """The low end of the estimate told to the user, in whole minutes: the writing (writing_minutes), plus making a
    video of that length with its pictures and clips (gathering_seconds), rounded to the nearest minute, at least 1.
    The scenes aren't written yet, so it counts one scene per 20 seconds and a 0.5 s breath between scenes.
    2 minutes of video: 120 s of speech in 6 scenes, 122.5 s with the 5 breaths, 3,675 frames -> 12 + 52.5 + 10 =
    74.5 s -> 1 minute of making + 2 of writing -> 3, told as "about 3–5 minutes". With 20 pictures and 6 clips:
    74.5 + 50 = 124.5 s -> 2 + 2 -> 4. 6 minutes: 203.9 s -> 3 + 6 -> 9."""
    speech_seconds = minutes * 60
    scenes = max(1, round(speech_seconds / SCENE_SECONDS))
    breaths = (scenes - 1) * timeline.BREATH
    frames = timeline.frame_count(speech_seconds + breaths, timeline.FPS)
    seconds = making_seconds(speech_seconds, frames) + gathering_seconds(images, clips)
    making = max(1, round(seconds / 60))
    return writing_minutes(minutes) + making


def library_pictures_left_out(lines: list[str], pictures: list[assets.Given]) -> tuple[list[str], list[str]]:
    """Decides which picture lines go to the job. A photo:<id> from the user's library that can't go in (only a small
    copy on this Mac, none at all, a video, an id the library doesn't have) is left out now, with why, so the chat can
    tell the user while they're here; every other line goes on, and the job fetches it. Gives (the lines kept, what
    was left out).
      ["photo:3F2A — us at the gate", "photo:5A11 — Tsomgo lake"], 5A11 with only a 360 px copy here ->
      (["photo:3F2A — us at the gate"], ["Tsomgo lake (photo:5A11 has only a small copy on this Mac (360 px); open
      it in Photos once so the full picture comes down)"])
      ["https://… — Red Fort"] -> kept unchecked: a web picture is the job's to fetch"""
    kept = []
    left_out = []
    for line, picture in zip(lines, pictures):
        if not picture.address.startswith("photo:"):
            kept.append(line)
            continue
        try:
            photos.library_copy(picture.address)
        except photos.PhotoError as e:
            left_out.append(f"{picture.words} ({e})")
            continue
        kept.append(line)
    return kept, left_out


def web_lines_left_out(lines: list[str], given: list[assets.Given], private: bool) -> tuple[list[str], list[str]]:
    """Decides which lines go to the job from a private chat (one that read a signed-in page). Such a chat fetches
    nothing from the web, so its web pictures and clips are left out now, with why, so the chat can tell the user
    (as the deck does: odie.making.deck); the user's own pictures go on. A public chat keeps every line. Gives (the
    lines kept, what was left out).
      private, ["https://… — Red Fort (Photo by A on Unsplash)", "photo:3F2A — us at the gate"] ->
      (["photo:3F2A — us at the gate"], ["Red Fort (not fetched: this chat read a signed-in page, …)"])
      not private, the same lines -> (both lines, [])"""
    if not private:
        return lines, []
    kept = []
    left_out = []
    for line, picture in zip(lines, given):
        if assets.is_web(picture.address):
            left_out.append(f"{picture.words} ({photos.PRIVATE_REFUSAL})")
            continue
        kept.append(line)
    return kept, left_out


def sounds_as_given(sounds) -> bool:
    """Decides whether the video gets sound effects, from the sounds argument as the model sent it: on unless it says
    off. Some models leave an optional argument null or send a boolean as text: None -> True (the default); True ->
    True; False -> False; "false", " False " or "no" -> False; "true" -> True."""
    if sounds is None:
        return True
    if isinstance(sounds, str):
        said = sounds.strip().lower()
        return said not in SOUNDS_OFF
    return bool(sounds)


def style_as_given(style) -> str:
    """The narration style as one line of at most MAX_STYLE_CHARACTERS, from the style argument as the model sent it:
    None or "" -> ""; "Calm.\n  Slow down on numbers. " -> "Calm. Slow down on numbers."; 400 characters -> the
    first 300."""
    words = chat.text_or_empty(style).split()
    one_line = " ".join(words)
    return one_line[:MAX_STYLE_CHARACTERS]


def aspect_as_given(aspect) -> str:
    """Decides the video's shape from the aspect argument as the model sent it: "vertical" (1080 x 1920, a reel) for
    "vertical", "portrait", "reel", "insta", "shorts" or "9:16", in any case and spacing; "landscape" (1920 x 1080,
    as every video before) for "landscape", "wide", "16:9", "", None, or any other word. " Reel " -> "vertical";
    "square" -> "landscape"."""
    said = chat.text_or_empty(aspect).strip().lower()
    if said in VERTICAL_WORDS:
        return "vertical"
    return "landscape"


def timed_seconds_as_given(value, minutes: int) -> int | None:
    """The timed segment's seconds from the argument as the model sent it, or None for no segment; ValueError, in
    words, for one that can't be. None, "" or 0 -> None; 60 or "60" -> 60; "soon" or -5 -> "… a whole number of
    seconds …"; 90 in a 1-minute video -> "… longer than the video …"."""
    if value is None or value == "" or value == 0:
        return None
    try:
        seconds = int(str(value).strip())
    except ValueError:
        seconds = -1
    if seconds <= 0:
        raise ValueError(f"timed_segment_seconds is a whole number of seconds, like 60 (got {value!r}).")
    if seconds > minutes * 60:
        raise ValueError(f"timed_segment_seconds is {seconds}, longer than the video ({minutes} min): ask for a "
                         "longer video or a shorter segment.")
    return seconds


async def make_video(topic: str, minutes: int = 2, brief: str = "", sources: list[str] | None = None,
                     images: list[str] | None = None, clips: list[str] | None = None, sounds: bool = True,
                     voice_name: str = "", style: str = "", aspect: str = "", timed_segment_seconds: int | None = None,
                     brand_kit: str = "", script: str = "", voices: list[dict] | None = None,
                     tool_context: ToolContext | None = None) -> dict:
    """Make a narrated, animated explainer video that plays in this chat. A separate writer makes the narration and
    the animation from your brief, in the background; it can't see this chat, the user's notes, memory or the web.
    topic: what the video is about, short ("How attention works").
    minutes: its length, from 1 to 6: the user's length, else 2.
    brief: the plan: who it's for and their level, the key points in order, the look, examples, numbers or formulas
    that must appear, and any facts you found. Up to 20,000 characters.
    sources: what the user gave, passed to the writer word for word (never retype it): "my message" (the user's
    latest message), a note's name or path in their vault, or a text file's path in Odie's workspace. Up to 5.
    images: pictures for the film, at most 20, each one line "address — what it shows": the address a tool gave
    (https://… from find_images, photo:<id>, upload:<id>, screenshot:<id>), then what the picture shows, its mood, its
    orientation if unusual, and a web picture's credit in brackets at the end. The writer sees only these words.
    For a reel, find web pictures and clips only when the topic needs a real one (a place, a person, a real thing);
    the writer draws the rest.
    clips: short stock clips, at most 6, the same way, with the https:// address find_clips gave.
    sounds: leave true; false only when the user asks for no sound effects.
    voice_name: leave empty; only when the user asks for a voice, one of the Settings engine's voices.
    style: leave empty; only when the user says how the narrator should sound, one line up to 300 characters, like
    "Curious science narrator. Calm, but lift slightly at the payoff. Slow down on numbers." Only OpenAI's voices
    follow it.
    aspect: leave empty (a wide video); "vertical" when the user says insta, reel, shorts, vertical or mobile (a
    1080 x 1920 reel; only the frame changes, its length is still `minutes`). Never put the aspect in the brief.
    timed_segment_seconds: leave empty; only when the brief says a segment must last exactly N seconds (a countdown
    character's 60 seconds inside a longer video): N. The writer marks that segment, and Odie fits its voice to exactly
    N seconds, first word to last; the rest of the video keeps its natural length.
    brand_kit: leave empty; only when a skill says to use its brand kit: that skill's name. The kit's fixed look,
    sounds and opening and closing scenes go in as they are, and the writer draws around them.
    script: leave empty; only for a dialogue video the user wrote: "my message" when they pasted it, else their
    script's note name or path, or a workspace file ("## Scene: …" headings, "SPEAKER: line" lines). The writer
    stages it word for word; never retype it, and the brief then says only the look and the cast's appearance.
    voices: with a script only, a voice for every speaker but the narrator: [{"id": "anna", "name": <a voice of the
    Settings engine>}].
    It returns at once. {"error": …}: fix exactly that and call again. {"result": …}: the video is being made; reply
    in one or two lines as the result says, and don't repeat the brief."""
    if find.browser_binary() is None:
        return {"error": NO_BROWSER}

    topic = chat.text_or_empty(topic)
    brief = chat.text_or_empty(brief)
    voice_name = chat.text_or_empty(voice_name)
    style = style_as_given(style)
    aspect = aspect_as_given(aspect)
    minutes = chat.minutes_as_given(minutes, DEFAULT_MINUTES)

    title = topic.strip()
    if not title:
        return {"error": NO_TOPIC}

    problem = chat.minutes_problem(minutes, MIN_MINUTES, timeline.MAX_MINUTES, WORD, DEFAULT_MINUTES)
    if problem:
        return {"error": problem}

    try:
        timed_seconds = timed_seconds_as_given(timed_segment_seconds, minutes)
    except ValueError as e:
        return {"error": str(e)}

    kit = None
    kit_name = chat.text_or_empty(brand_kit).strip()
    if kit_name:
        try:
            kit = brand.find(kit_name)
        except brand.KitProblem as e:
            return {"error": str(e)}
        problem = brand.segment_problem(kit, timed_seconds)
        if problem:
            return {"error": problem}

    dialogue_data = None
    if voices and not chat.text_or_empty(script).strip():
        return {"error": VOICES_NEED_SCRIPT}
    if chat.text_or_empty(script).strip():
        if timed_seconds is not None or kit is not None:
            return {"error": DIALOGUE_ALONE}
        try:
            dialogue_data = dialogue_as_given(chat.text_or_empty(script).strip(), voices, jobs.hooks["store"])
        except (ValueError, making_sources.SourceProblem) as e:
            return {"error": str(e)}

    problem = chat.brief_problem(brief, WORD, MAX_BRIEF_CHARACTERS)
    if problem:
        return {"error": f"{problem} {chat.USE_SOURCES}"}

    try:
        references = making_sources.sources_as_given(sources)
        found = making_sources.resolve(references, jobs.hooks["store"])
    except making_sources.SourceProblem as e:
        return {"error": str(e)}

    try:
        pictures, moving = assets.parse(images, clips)
    except assets.AssetProblem as e:
        return {"error": str(e)}
    private = bool(private_sites())
    image_lines = assets.lines_as_given(images, "images")
    image_lines, pictures_left_out = web_lines_left_out(image_lines, pictures, private)
    kept_pictures, _ = assets.parse(image_lines, None)  # the kept lines read again, so the next check lines up
    image_lines, library_left_out = await asyncio.to_thread(library_pictures_left_out, image_lines, kept_pictures)
    clip_lines = assets.lines_as_given(clips, "clips")
    clip_lines, clips_left_out = web_lines_left_out(clip_lines, moving, private)
    left_out = library_left_out + pictures_left_out + clips_left_out
    given = {"images": image_lines, "clips": clip_lines}

    voice_id = ""
    if voice_name.strip():
        try:
            voice_id = voice.voice_in_chosen_engine(jobs.hooks["store"], voice_name)["id"]
        except ValueError as e:
            return {"error": str(e)}

    folder = chat.free_folder(workspace() / kind.FOLDER, chat.slug_of(title, WORD))
    folder.mkdir(parents=True)
    whole_brief = making_sources.brief_with_sources(brief, found)
    data = {"given": given, "private": sorted(private_sites())}  # the job fetches as this chat would
    data["sounds"] = sounds_as_given(sounds)  # the making step mixes the page's sound cues only when this is True
    data["style"] = style  # how the OpenAI narrator sounds; "" keeps Odie's usual (odie.voice.tts_style)
    data["aspect"] = aspect  # "landscape" or "vertical": the stage's size (odie.video.timeline.size_of)
    if timed_seconds is not None:  # a segment of exactly that many seconds (odie.video.timed)
        data["timed_segment"] = {"seconds": timed_seconds, "tolerance": timed.TOLERANCE}
    if kit is not None:  # the kit as it is now, copied into the job's folder (odie.video.brand)
        data["brand_kit"] = brand.snapshot(kit, folder)
    if dialogue_data is not None:  # the user's script, staged word for word, each speaker in their voice
        data["dialogue"] = dialogue_data
    job = jobs.Job(kind="video", slug=folder.name, title=title, topic=title, minutes=minutes, brief=whole_brief,
                   session_id=session_id_of(tool_context), voice_name=voice_id, folder=folder, data=data)
    place = jobs.submit(job)
    low = minutes_to_make(minutes, len(image_lines), len(clip_lines))
    high = low + ESTIMATE_SPREAD
    reply = chat.reply(place, low, high, DOING)
    if left_out:
        told = LEFT_OUT.format(pictures="; ".join(left_out))
        reply = f"{reply} {told}"
    return {"result": reply}


DIALOGUE_ALONE = ("A dialogue video (a script) can't have a timed segment or a brand kit yet: leave "
                  "timed_segment_seconds and brand_kit empty.")


VOICES_NEED_SCRIPT = ("voices are for a dialogue video: give its script too, or use voice_name for one narrator's "
                      "voice.")


def voices_as_given(voices) -> list:
    """The voices list the model meant: None -> []; JSON text -> read as below; a list -> as it is; a mapping of
    speaker to voice ({"anna": "Bella"}) -> [{"id": "anna", "name": "Bella"}]."""
    if voices is None:
        return []
    if isinstance(voices, str):
        try:
            voices = json.loads(voices)
        except ValueError:
            raise ValueError('voices is a list: [{"id": "anna", "name": "<a voice>"}].') from None
    if isinstance(voices, dict):
        return [{"id": speaker, "name": name} for speaker, name in voices.items()]
    return voices


def dialogue_as_given(script_reference: str, voices, store) -> dict:
    """A dialogue video's script and voices, checked before anything is queued: the script read as sources are (a
    note or a workspace file) and parsed (odie.video.dialogue.parse), every speaker but the narrator given a voice of
    the engine chosen in Settings, kept by its id. Returns {"script": [...], "voices": {speaker: voice id}}; raises
    ValueError (or SourceProblem) in words to fix: a speaker with no voice ("ben"), a voice of another engine, a
    script with no lines."""
    [source] = making_sources.resolve([script_reference], store)
    script = dialogue.parse(source.text)
    problem = dialogue.script_problem(script)
    if problem:
        raise ValueError(problem)
    named = dialogue.voices_by_speaker(voices_as_given(voices))
    missing = dialogue.missing_voices(script, named)
    if missing:
        raise ValueError(f"Every speaker but the narrator needs a voice; none for: {', '.join(missing)}. Add "
                         '{"id": "<speaker>", "name": "<a voice of the Settings engine>"} to voices.')
    by_id = {speaker: voice.voice_in_chosen_engine(store, name)["id"] for speaker, name in named.items()}
    return {"script": script.as_data(), "voices": by_id}


TOOLS = [FunctionTool(make_video)]
