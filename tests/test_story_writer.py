"""The story writer: one focused turn, handed only story_writer.md and one tool (submit_story, the whole script as
JSON), that ends with a checked script Odie's code can render, or a WriterFailed that says why.

check_script decides whether a script can be rendered (every speaker in the cast, every sound in the library, known
levels, at most one bed and one music bed in a scene, pauses within limits, the prelude opening on sound) and gives
its problems in words. The length is checked apart: a script outside ±10% of the asked minutes is refused once, then
accepted with a note for the job.

The tests use a stand-in for runner.focused_turn that calls the tool by name, as a model would."""
import copy
import json

import pytest
from google.adk.events.event_actions import EventActions

from odie.making import story_writer as writer
from odie.making import writer as harness

ACCEPTED = {"result": "Accepted."}
CATALOGUE = [
    {"id": "ambience/ocean-surf", "name": "Ocean Surf", "category": "Ambience", "kind": "loop", "seconds": 30.0},
    {"id": "ambience/night-forest", "name": "Night Forest", "category": "Ambience", "kind": "loop", "seconds": 30.0},
    {"id": "animals/seagulls", "name": "Seagulls", "category": "Animals", "kind": "hit", "seconds": 4.0},
    {"id": "foley/door-creak", "name": "Door Creak", "category": "Foley", "kind": "hit", "seconds": 2.0},
    {"id": "stingers/dark-hit", "name": "Dark Hit", "category": "Stingers", "kind": "hit", "seconds": 3.0},
    {"id": "jingles/borealis", "name": "Borealis", "category": "Jingles", "kind": "music", "seconds": 60.0},
]
CAST = [
    {"id": "narrator", "name": "Narrator", "voice": "Fairy Godmother", "about": "an outside storyteller"},
    {"id": "keeper", "name": "The keeper", "voice": "Old Mortlake", "about": "the old lighthouse keeper"},
]


def words(count: int) -> str:
    """A line of exactly `count` spoken words."""
    return " ".join(["tide"] * count) + "."


def good_script() -> dict:
    """A two-minute story: a 3 s prelude sound, 4 lines, a crossfade, then 5 more lines. Each line is 29 words (12 s at
    145 words a minute) plus the 0.4 s gap after it: 3 + 4 × 12.4 + 2.5 + 5 × 12.4 = 117.1 s, within 108–132."""
    return {
        "title": "The Lighthouse at Rook Point",
        "scenes": [
            {"title": "Prelude", "bed": {"sound": "ambience/ocean-surf", "level": "normal"},
             "music": {"sound": "jingles/borealis", "level": "low"},
             "lines": [{"sound": "animals/seagulls", "level": "low", "lead": 3.0}]
             + [{"speaker": "narrator", "text": words(29)} for _ in range(3)]
             + [{"speaker": "keeper", "text": words(29), "sound_after": "foley/door-creak"}],
             "transition": {"kind": "crossfade", "seconds": 2.5}},
            {"title": "The storm", "bed": {"sound": "ambience/night-forest", "level": "up front"},
             "lines": [{"speaker": "keeper", "text": words(29)} for _ in range(5)]},
        ],
    }


def problems(script: dict, minutes: int = 2) -> list[str]:
    return writer.check_script(script, CATALOGUE, CAST, minutes)


# check_script: what can and can't be rendered.

def test_a_good_script_has_no_problems_and_is_about_two_minutes():
    assert problems(good_script()) == []
    assert writer.estimated_seconds(writer.parse_script(good_script())) == pytest.approx(117.1)


def test_an_unknown_sound_is_named_with_where_it_is():
    script = good_script()
    script["scenes"][0]["lines"][0]["sound"] = "animals/owl"
    assert problems(script) == [
        'Scene 1 ("Prelude"), line 1: there is no sound "animals/owl" in the library. Use an id from the sound list.']


def test_an_unknown_speaker_is_named_with_the_cast():
    script = good_script()
    script["scenes"][1]["lines"][2]["speaker"] = "captain"
    assert problems(script) == [
        'Scene 2 ("The storm"), line 3: "captain" isn\'t in the cast. The speakers are: narrator, keeper.']


def test_two_beds_in_a_scene_are_refused():
    script = good_script()
    script["scenes"][1]["bed"] = [{"sound": "ambience/ocean-surf"}, {"sound": "ambience/night-forest"}]
    assert problems(script) == [
        'Scene 2 ("The storm"): one bed at a time. Give "bed" one sound (and "music" one more at most).']


def test_an_unknown_level_word_is_refused():
    script = good_script()
    script["scenes"][0]["bed"]["level"] = "loud"
    assert problems(script) == [
        'Scene 1 ("Prelude"), the bed: the level "loud" isn\'t one of low, normal, up front.']


def test_pauses_and_leads_beyond_their_limits_are_refused():
    script = good_script()
    script["scenes"][0]["lines"][1]["pause_after"] = 9
    script["scenes"][0]["lines"][0]["lead"] = 12
    assert problems(script) == [
        'Scene 1 ("Prelude"), line 1: the lead is 12 seconds; it can be from 2 to 6 for the prelude\'s opening sound.',
        'Scene 1 ("Prelude"), line 2: pause_after is 9 seconds; it can be from 0 to 4.',
    ]


def test_the_prelude_must_open_on_sound_then_the_narrator():
    script = good_script()
    script["scenes"][0]["lines"] = script["scenes"][0]["lines"][1:]
    assert problems(script)[0] == ('Scene 1 ("Prelude"): the story opens on sound. Make its first line a sound with a '
                                   'lead of 2 to 6 seconds, then the narrator sets the scene.')
    keeper_first = good_script()
    lines = keeper_first["scenes"][0]["lines"]
    lines[1], lines[4] = lines[4], lines[1]
    assert problems(keeper_first) == [
        'Scene 1 ("Prelude"): the narrator speaks first, setting the place, time and mood; here "keeper" does.']


def test_a_stinger_transition_needs_a_known_sound_and_a_crossfade_two_to_three_seconds():
    script = good_script()
    script["scenes"][0]["transition"] = {"kind": "stinger", "sound": "stingers/none"}
    unknown = ('Scene 1 ("Prelude"), the transition: there is no sound "stingers/none" in the library. Use an id from '
               'the sound list.')
    assert problems(script) == [unknown]
    script["scenes"][0]["transition"] = {"kind": "crossfade", "seconds": 6}
    assert problems(script) == [
        'Scene 1 ("Prelude"), the transition: a crossfade is 2 to 3 seconds, not 6.']
    script["scenes"][0]["transition"] = {"kind": "wipe"}
    assert problems(script) == [
        'Scene 1 ("Prelude"), the transition: "wipe" isn\'t one of crossfade, stinger, silence.']


def test_a_bed_is_a_loop_the_music_is_music_and_a_cue_is_never_music():
    script = good_script()
    script["scenes"][0]["bed"] = {"sound": "foley/door-creak"}
    script["scenes"][0]["music"] = {"sound": "ambience/ocean-surf"}
    script["scenes"][0]["lines"][4]["sound_after"] = "jingles/borealis"
    script["scenes"][0]["transition"] = {"kind": "stinger", "sound": "jingles/borealis"}
    assert problems(script) == [
        'Scene 1 ("Prelude"), the bed: "foley/door-creak" is a hit, played once; a bed is a loop from the list.',
        'Scene 1 ("Prelude"), the music: "ambience/ocean-surf" is a loop; music is a sound marked music in the list.',
        ('Scene 1 ("Prelude"), line 5: "jingles/borealis" is music; a sound in the lines is a hit (or a loop, which '
         'plays once for up to 8 seconds).'),
        ('Scene 1 ("Prelude"), the transition: "jingles/borealis" is music; a stinger is a hit (or a loop, which '
         'plays once for up to 8 seconds).'),
    ]


def test_a_loop_may_open_the_prelude_as_a_cue():
    """Seagulls crying, or a crowd's murmur rising, before the narrator speaks: a loop played once, cut at 8 s."""
    script = good_script()
    script["scenes"][0]["lines"][0]["sound"] = "ambience/night-forest"
    assert problems(script) == []


def test_a_bed_or_transition_written_as_plain_text_is_read_as_its_id_or_kind():
    script = good_script()
    script["scenes"][0]["bed"] = "ambience/ocean-surf"
    script["scenes"][0]["transition"] = "crossfade"
    assert problems(script) == []
    story = writer.parse_script(script)
    assert story.scenes[0].bed == writer.Sound("ambience/ocean-surf", "normal")
    assert story.scenes[0].transition == writer.Transition("crossfade", writer.DEFAULT_TRANSITION_SECONDS, None)
    script["scenes"][0]["bed"] = 42
    script["scenes"][0]["transition"] = ["crossfade"]
    assert problems(script) == [
        'Scene 1 ("Prelude"), the bed: write it as {"sound": id, "level": word}, not 42.',
        'Scene 1 ("Prelude"), the transition: write it as {"kind": "crossfade", "seconds": 2.5}, not [\'crossfade\'].',
    ]


def test_a_line_with_nothing_to_say_and_a_script_that_is_not_json():
    script = good_script()
    script["scenes"][1]["lines"][0]["text"] = "  "
    assert problems(script) == ['Scene 2 ("The storm"), line 1: the line has nothing to say.']
    assert writer.script_problems_in("not json", CATALOGUE, CAST)[0].startswith("The script isn't JSON:")


def test_the_length_is_checked_within_ten_percent():
    assert writer.length_problem(writer.parse_script(good_script()), 2) is None
    short = good_script()
    short["scenes"][1]["lines"] = short["scenes"][1]["lines"][:1]  # 3 + 49.6 + 2.5 + 12.4 = 67.5 s
    too_short = ("The story is too short: about 1:08 for 2 minutes; anything from 1:48 to 2:12 is fine (about 145 "
                 "words a minute, plus the pauses, leads and transitions). Add a beat or a line of dialogue to a scene.")
    assert problems(short) == [too_short]
    long = good_script()
    long["scenes"][1]["lines"] = long["scenes"][1]["lines"] * 2  # 117.1 + 62 = 179.1 s
    assert "too long: about 2:59 for 2 minutes" in problems(long)[0]


# The writer's turn.

class Context:
    def __init__(self):
        self.actions = EventActions()


class Turn:
    """Stands in for runner.focused_turn: records what it is handed, plays `script(turn)`, then asks follow_up once."""

    def __init__(self, script):
        self.script = script
        self.prompt = ""
        self.instruction = ""
        self.said = []
        self.nudge = None
        self.tools = []

    async def __call__(self, prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
        self.prompt = prompt
        self.instruction = instruction
        self.tools = tools
        await self.script(self)
        if follow_up is not None:
            self.nudge = follow_up()
        return ""

    async def submit(self, script):
        by_name = {tool.__name__: tool for tool in self.tools}
        out = await by_name["submit_story"](json.dumps(script), tool_context=Context())
        self.said.append(out)
        return out


async def write(turn, minutes=2, engine=""):
    request = writer.Request(genre="mystery", premise="A keeper hears a ship that isn't there.", cast=CAST,
                             narrator="narrator", accent="British", minutes=minutes, brief="Slow and eerie.",
                             engine=engine)
    return await writer.write(request, CATALOGUE, "ambience/ocean-surf · 30s · loop", turn)


async def test_a_good_script_is_accepted_and_parsed_for_the_making():
    turn = Turn(lambda turn: turn.submit(good_script()))
    written = await write(turn)
    assert turn.said == [ACCEPTED]
    assert written.title == "The Lighthouse at Rook Point" and written.note == ""
    first = written.scenes[0]
    assert first.bed == writer.Sound("ambience/ocean-surf", "normal")
    assert first.music == writer.Sound("jingles/borealis", "low")
    assert first.lines[0] == writer.Cue(sound="animals/seagulls", level="low", lead=3.0)
    assert first.lines[4] == writer.Speech(speaker="keeper", text=words(29), pause_after=writer.LINE_GAP,
                                           sound_after="foley/door-creak")
    assert first.transition == writer.Transition("crossfade", 2.5, None)
    assert written.scenes[1].music is None
    assert written.script == good_script()  # the script as accepted, for the job's script.json


async def test_an_unrenderable_script_is_refused_with_its_problems_then_fixed():
    bad = good_script()
    bad["scenes"][0]["lines"][0]["sound"] = "animals/owl"
    bad["scenes"][1]["lines"][0]["speaker"] = "captain"

    async def script(turn):
        await turn.submit(bad)
        await turn.submit(good_script())

    turn = Turn(script)
    await write(turn)
    error = turn.said[0]["error"]
    assert 'no sound "animals/owl"' in error and '"captain" isn\'t in the cast' in error
    assert turn.said[1] == ACCEPTED


async def test_three_unrenderable_scripts_fail_the_job():
    bad = good_script()
    bad["scenes"][0]["lines"][0]["sound"] = "animals/owl"

    async def script(turn):
        for _ in range(3):
            await turn.submit(bad)

    with pytest.raises(harness.WriterFailed) as failed:
        await write(Turn(script))
    assert "no sound \"animals/owl\"" in str(failed.value)


async def test_the_length_is_refused_once_then_accepted_with_a_note():
    short = good_script()
    short["scenes"][1]["lines"] = short["scenes"][1]["lines"][:1]

    async def script(turn):
        await turn.submit(short)
        await turn.submit(short)

    turn = Turn(script)
    written = await write(turn)
    assert turn.said[0]["error"].startswith("The story is too short")
    assert turn.said[1] == ACCEPTED
    assert written.note == "The story came out at about 1:08 for 2 minutes (asked once to fix its length)."


async def test_the_prompt_carries_the_brief_the_cast_and_the_sound_list():
    turn = Turn(lambda turn: turn.submit(good_script()))
    await write(turn)
    assert "Genre: mystery" in turn.prompt
    assert "A keeper hears a ship that isn't there." in turn.prompt
    assert "- narrator: Narrator (an outside storyteller)" in turn.prompt
    assert "- keeper: The keeper (the old lighthouse keeper)" in turn.prompt
    assert "The narrator is an outside storyteller" in turn.prompt
    assert "Accent: British" in turn.prompt
    assert "2 minutes, about 290 spoken words" in turn.prompt
    assert "ambience/ocean-surf · 30s · loop" in turn.prompt
    assert "owls" in turn.instruction and "temple bell" in turn.instruction  # the art director's examples
    assert "one bed and one music bed" in turn.instruction


async def test_a_narrator_inside_the_story_is_told_to_speak_in_the_first_person():
    request = writer.Request(genre="horror", premise="p", cast=CAST, narrator="keeper", accent="American",
                             minutes=2, brief="")
    prompt = writer.prompt_for(request, "listing")
    assert "The narrator is keeper, in the story: they tell it in the first person" in prompt


def test_the_level_words_are_forgiving_about_spelling():
    script = copy.deepcopy(good_script())
    script["scenes"][1]["bed"]["level"] = "Up-front"
    assert problems(script) == []
    assert writer.parse_script(script).scenes[1].bed.level == "up front"


def test_each_engine_has_its_own_pace():
    """Phonon's voices read their lines at 166–246 words a minute (measured, its median about 208); an engine not
    measured keeps a storyteller's 145."""
    assert writer.words_per_minute("phonon") == 200
    assert writer.words_per_minute("kokoro") == writer.DEFAULT_WORDS_PER_MINUTE == 145
    assert writer.words_per_minute("") == 145


async def test_a_phonon_story_is_written_and_checked_at_phonons_pace():
    """The same 29-word lines are 8.7 s each at 200 words a minute: the two-minute script comes out at 1:27, too
    short; the prompt asks for 400 words."""
    async def script(turn):
        await turn.submit(good_script())
        await turn.submit(good_script())

    turn = Turn(script)
    written = await write(turn, engine="phonon")
    assert "2 minutes, about 400 spoken words (200 a minute;" in turn.prompt
    assert turn.said[0]["error"].startswith("The story is too short: about 1:27 for 2 minutes")
    assert "about 200 words a minute" in turn.said[0]["error"]
    assert written.note.startswith("The story came out at about 1:27 for 2 minutes")
