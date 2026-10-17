"""The podcast writer: one focused model turn, in the background, that writes a podcast's script for two hosts.

It runs on the shared writer harness (odie.making.writer). It sees only podcast_writer.md (the hosts, the sound, the
length, the script's shape) and one tool, submit_podcast, which takes the title and the whole script at once. The
script is checked for its shape (parse_script: two hosts, one turn per line, at most 60 turns) and its length (about
140 words a minute, give or take 40%). A problem goes back to the writer to fix. An accepted script or a third refusal
ends the turn there and then; a writer that stops without either is nudged once, in the same session. The turn ends
with the accepted script (Written) or WriterFailed."""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from odie.agent.tools.media import plain_speech
from odie.making import writer as harness
from odie.making.chat import text_or_empty

INSTRUCTION = Path(__file__).with_name("podcast_writer.md").read_text(encoding="utf-8")

MAX_TURNS = 60
WORDS_PER_MINUTE = 140
LENGTH_SPREAD = 0.4  # a script within 40% of the words its minutes make is fine

# "Name:" at the start of a line: one to three words in any script, starting with a letter, with no digits ("At 10:30"
# and "Step 1:" aren't names).
HOST_LABEL = re.compile(r"^\s*\**\s*([^\W\d_][^\s:\d*]{0,20}(?: [^\W\d_][^\s:\d*]{0,20}){0,2})\s*\**\s*:\s*\**\s*(.*)$")
TWO_HOSTS = "A podcast has two hosts, a woman and then a man"
NO_LABELS = ('Write each line as Host A: or Host B: and what they say (for example, "Host A: Today we\'re looking '
             'at…").')

PLAN_THEN_WRITE = "Plan in a few lines, then call submit_podcast with the title and the whole script."
LINES = harness.Lines(
    nudge=("You haven't called submit_podcast yet. Stop planning and don't count words: write the script now, as it "
           "is, and call submit_podcast with the title and the whole script."),
    nudge_after_problem=("submit_podcast hasn't accepted the script yet. Its last answer was: {problem} Fix exactly "
                         "that and call submit_podcast again with the title and the whole fixed script."),
    never_submitted="I couldn't write the podcast's script (the writer stopped without one).",
    not_passed="I couldn't write a script that passed its check: {problem}",
)
SUBMIT_DOC = ("Submit the whole podcast at once: title (short, about the topic; never the hosts) and script (one turn "
              'per line, "Host A: what they say" or "Host B: what they say", Host A first). It checks the script\'s '
              "shape and length.\n"
              '{"error": …}: fix exactly that and call submit_podcast again with the whole fixed script.\n'
              '{"result": "Accepted."}: the podcast is done.')
SUBMIT_FIELDS = {"title": str, "script": str}


@dataclass
class Written:
    """The accepted podcast: its title and its turns, [(host, plain speech)], in order."""
    title: str
    turns: list[tuple[str, str]]


def labelled_line(raw: str) -> tuple[str | None, str]:
    """A script line split into who says it and what they say, when it starts with a name and a colon: "Host A:
    Hello." -> ("Host A", "Hello."); "**Rohan:** Hi" -> ("Rohan", "Hi"); "At 10:30 we met." -> (None, the line)."""
    match = HOST_LABEL.match(raw)
    if match is None:
        return None, raw
    return match.group(1).strip(), match.group(2)


def parse_script(script: str) -> list[tuple[str, str]]:
    """A podcast script, one turn per line ("Name: what they say"), as [(host, plain speech)]. The first two names are
    the hosts. A line without one of them continues the turn before, even with a colon in it ("At 10:30 we…",
    "Note: …"), unless it names a third speaker more than once. ValueError, in plain words, unless there are exactly two
    hosts with something to say and at most 60 turns: "Host A: Hi.\\nHost B: Hello." -> [("Host A", "Hi."), ("Host B",
    "Hello.")]; "Host A: Hi. Host B: Hello." on one line -> "… this script has 1." (it is all Host A's)."""
    lines = []
    for raw in text_or_empty(script).splitlines():
        if raw.strip():
            name, text = labelled_line(raw)
            lines.append((name, text, raw))
    times_named = Counter(name for name, _text, _raw in lines if name)

    hosts: list[str] = []
    turns: list[list[str]] = []
    for name, text, raw in lines:
        if name and name not in hosts and len(hosts) < 2:
            hosts.append(name)
        if name in hosts:
            turns.append([name, text])
        elif name and times_named[name] > 1:
            raise ValueError(f"{TWO_HOSTS}; this script also has {name}.")
        elif turns:
            turns[-1][1] += " " + raw
        else:
            raise ValueError(NO_LABELS)

    if len(hosts) != 2:
        raise ValueError(f"{TWO_HOSTS}; this script has {len(hosts)}.")
    if len(turns) > MAX_TURNS:
        raise ValueError(f"A podcast has at most {MAX_TURNS} turns; this script has {len(turns)}.")

    spoken = []
    for name, text in turns:
        speech = plain_speech(text)
        if speech:
            spoken.append((name, speech))
    speakers = {name for name, _speech in spoken}
    if len(speakers) != 2:
        raise ValueError(f"{TWO_HOSTS}, and each needs something to say (a link or code alone isn't spoken).")
    return spoken


def minutes_word(minutes: int) -> str:
    """1 -> "minute"; 2 -> "minutes"."""
    if minutes == 1:
        return "minute"
    return "minutes"


def spoken_words(turns: list[tuple[str, str]]) -> int:
    """The words the hosts say, labels left out: [("Host A", "Hello there."), ("Host B", "Hi.")] -> 3."""
    return sum(len(speech.split()) for _host, speech in turns)


def length_problem(turns: list[tuple[str, str]], minutes: int) -> str | None:
    """Decides whether the script is about as long as asked: 140 words a minute, anything within 40% either way is
    fine. 2 minutes -> about 280 words, 168 to 392 fine: 300 words -> None; 40 -> "The script is too short: about 280
    words for 2 minutes; this is 40. Anything from 168 to 392 words is fine: add a point, …"; 600 -> "… too long …: cut
    a point or shorten the turns, …"."""
    target = minutes * WORDS_PER_MINUTE
    lowest = round(target * (1 - LENGTH_SPREAD))
    highest = round(target * (1 + LENGTH_SPREAD))
    words = spoken_words(turns)
    if lowest <= words <= highest:
        return None
    said = (f"about {target} words for {minutes} {minutes_word(minutes)}; this is {words}. Anything from {lowest} to "
            f"{highest} words is fine")
    again = "then call submit_podcast again with the whole script."
    if words < lowest:
        return f"The script is too short: {said}: add a point, an example or a question, {again}"
    return f"The script is too long: {said}: cut a point or shorten the turns, {again}"


def submission_problem(script: str, minutes: int) -> str | None:
    """Decides whether a script can be accepted: the first problem as words to fix, or None. Its shape first
    (parse_script's words: both hosts on one line -> "A podcast has two hosts, a woman and then a man; this script has
    1."), then its length (length_problem). Ten turns of 28 words for 2 minutes -> None."""
    try:
        turns = parse_script(script)
    except ValueError as e:
        return str(e)
    return length_problem(turns, minutes)


def prompt_for(topic: str, minutes: int, brief: str) -> str:
    """The writer's whole message: the topic, the length in minutes and in words (140 a minute: 4 minutes -> about 560
    words, given as a guide, not a count), the brief, and what to do."""
    words = minutes * WORDS_PER_MINUTE
    brief_text = brief.strip()
    if not brief_text:
        brief_text = "(none: use what you know about the topic)"
    return (f"Topic: {topic}\n"
            f"Length: {minutes} {minutes_word(minutes)}, roughly {words} words of script (a guide, not a count).\n\n"
            f"Brief:\n{brief_text}\n\n"
            f"{PLAN_THEN_WRITE}")


def tools_for(desk: harness.Desk, minutes: int) -> list:
    """The writer's one tool, submit_podcast (title, script), built by the shared harness on `desk`. Its check is
    submission_problem for this length; accepting makes the Written podcast, the title falling back to the topic."""

    async def check(fields: dict) -> str | None:
        script = text_or_empty(fields["script"])
        return submission_problem(script, minutes)

    def accept(fields: dict) -> Written:
        title = harness.title_given(fields["title"], desk.topic)
        turns = parse_script(text_or_empty(fields["script"]))
        return Written(title=title, turns=turns)

    return [harness.submit_tool(desk, "submit_podcast", SUBMIT_DOC, SUBMIT_FIELDS, check, accept)]


async def write(topic: str, minutes: int, brief: str, turn) -> Written:
    """Writes the podcast in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)` is
    runner.focused_turn in Odie. Returns the accepted script; raises WriterFailed when there's none, with the podcast's
    words (LINES), or the harness's time-limit line (see odie.making.writer.write)."""
    desk = harness.Desk(topic=topic)
    [tool] = tools_for(desk, minutes)
    return await harness.write(desk, prompt_for(topic, minutes, brief), INSTRUCTION, tool, LINES, turn)
