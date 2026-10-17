"""The video writer: one focused model turn, in the background, that writes an explainer video's narration and page.

It runs on the shared writer harness (odie.making.writer). It sees only writer.md (the page contract, the kit, the
worked example, the style) and one tool, submit_video, which takes the title, the narration and the whole page at
once. Every page sent is kept in the job's folder (pages/page-1.html, page-2.html, …), then checked: its size, the
narration, and the page drawn in a browser. A problem goes back to the writer to fix. An accepted video, a third
refusal or a browser that fails ends the turn there and then, with no more model calls. A writer that stops without
any of those is nudged once, in the same session. The turn ends with the accepted video (Written) or WriterFailed."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from odie.browser.engine import BrowserError, BrowserTimeout
from odie.making import writer as harness
from odie.making.chat import text_or_empty
from odie.video import page as video_page
from odie.video import timeline
from odie.video.limits import narration_problem, page_problem

INSTRUCTION = Path(__file__).with_name("writer.md").read_text(encoding="utf-8")

HANG = "The page didn't finish drawing in time (a loop that never ends?): "
NOT_A_LIST = ('narration is a list of strings, one string of plain speech per scene, in order: ["The first scene\'s '
              'words.", "The second scene\'s words."]')
BROWSER_FAILED = "The browser failed while checking the page."  # a BrowserError with no words of its own
PLAN_THEN_WRITE = "Plan in a few lines, then call submit_video with the title, the narration and the whole page."
LINES = harness.Lines(
    nudge=("You haven't called submit_video yet. Stop planning and don't count words: write the narration and the "
           "page now, as they are, and call submit_video with the title, the narration and the whole page."),
    nudge_after_problem=("submit_video hasn't accepted the video yet. Its last answer was: {problem} Fix exactly that "
                         "and call submit_video again with the title, the whole narration and the whole fixed page."),
    never_submitted="I couldn't write the video's page (the writer stopped without one).",
    not_passed="I couldn't write a page that passed its check: {problem}",
)
SUBMIT_DOC = ("Submit the whole video at once: title (the topic, short), narration (one string of plain speech per "
              "scene,\n"
              "in order) and page (the whole page: the HTML body, one <script> that calls Video.scenes([...]) once, "
              "with one\n"
              "scene per narration string). It checks the narration and draws the page.\n"
              '{"error": …}: fix exactly that and call submit_video again with the whole narration and the whole '
              "fixed page.\n"
              '{"result": "Accepted."}: the video is done.')  # what the writer reads, as it read before the harness
SUBMIT_FIELDS = {"title": str, "narration": list[str], "page": str}


@dataclass
class Written:
    """The accepted video: its title, one string of narration per scene, and the page body that draws them."""
    title: str
    narration: list[str]
    body: str


@dataclass(kw_only=True)
class Desk(harness.Desk):
    """The shared desk (odie.making.writer.Desk), plus where this video's submitted pages are kept."""
    pages: Path


def next_page_name(folder: Path) -> str:
    """The first free page name in the folder: nothing kept yet -> "page-1"; page-1 and page-2 there -> "page-3"."""
    n = 1
    while (folder / f"page-{n}.html").exists():
        n += 1
    return f"page-{n}"


def keep_page(folder: Path, body: str) -> None:
    """Keep a submitted page in the job's pages folder under the next free name, before it is checked, so every try
    (refused ones too) can be looked at afterwards: the first submit -> pages/page-1.html."""
    folder.mkdir(parents=True, exist_ok=True)
    name = next_page_name(folder)
    (folder / f"{name}.html").write_text(body, encoding="utf-8")


def prompt_for(topic: str, minutes: int, brief: str, listing: str = "") -> str:
    """The writer's whole message: the topic, the length in minutes and in words (140 a minute: 2 minutes -> about
    280 words, given as a guide, not a count), the brief, the video's pictures and clips by name (`listing`, from
    odie.video.assets.listing; nothing when there are none), and what to do."""
    words = minutes * timeline.WORDS_PER_MINUTE
    unit = "minutes"
    if minutes == 1:
        unit = "minute"
    brief_text = brief.strip()
    if not brief_text:
        brief_text = "(none: use what you know about the topic)"
    pictures = ""
    if listing.strip():
        pictures = f"{listing.strip()}\n\n"
    return (f"Topic: {topic}\n"
            f"Length: {minutes} {unit}, roughly {words} words of narration (a guide, not a count).\n\n"
            f"Brief:\n{brief_text}\n\n"
            f"{pictures}"
            f"{PLAN_THEN_WRITE}")


def narration_as_given(narration):
    """The narration the model meant. Some models send the list as JSON text: '["One.", "Two."]' -> ["One.", "Two."].
    Anything else is passed on unchanged for the check to judge: ["One."] -> ["One."]; "One." or '{"a": "b"}' -> the
    same text, refused there as not a list."""
    if not isinstance(narration, str):
        return narration
    try:
        parsed = json.loads(narration)
    except ValueError:
        return narration
    if is_list_of_strings(parsed):
        return parsed
    return narration


def is_list_of_strings(value) -> bool:
    """Decides whether the narration has the shape of one: ["One.", "Two."] -> True; [] -> True (refused later as no
    narration); "One." -> False; ["One.", 2] -> False."""
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) for item in value)


# A picture or clip named in the page: s.photo("img1", s.clip('clip2', s.texture(`img3`) or s.image("img4"), the first
# argument a plain string (a name built in a variable or a `${...}` template isn't read here; the kit tells those).
NAME_USED = re.compile(r"""\bs\.(photo|clip|texture|image)\(\s*(["'`])([^"'`$\\\n]+)\2""")
STAPLE_START = "<script>Video.assets("
STAPLE_END = ")</script>"


def stapled_names(assets_script: str) -> tuple[list[str], list[str]]:
    """The names of the pictures and of the clips stapled into the page (odie.video.assets.staple's
    `<script>Video.assets({...})</script>`), in order: the only names the page can draw. A staple of img1, img3 and
    clip1 -> (["img1", "img3"], ["clip1"]); no staple ("") -> ([], [])."""
    if not assets_script:
        return [], []
    registry = json.loads(assets_script.removeprefix(STAPLE_START).removesuffix(STAPLE_END))
    pictures = []
    clips = []
    for name, entry in registry.items():
        if entry["kind"] == "clip":
            clips.append(name)
        else:
            pictures.append(name)
    return pictures, clips


def is_whole_series(names: list[str]) -> bool:
    """Decides whether names run 1 to N with none missing, so "first…last" says them all: img1, img2, img3 -> True;
    img1, img3, img4 -> False (img2 was left out, and "img1…img4" would claim it)."""
    prefix = names[0].rstrip("0123456789")
    series = [f"{prefix}{number}" for number in range(1, len(names) + 1)]
    return names == series


def names_in_words(names: list[str]) -> str:
    """Names as a reader says them: ["clip1"] -> "clip1"; ["img1", "img2"] -> "img1 and img2"; a whole series of three
    or more -> "img1…img8"; a broken one -> "img1, img3 and img4"."""
    if len(names) == 1:
        return names[0]
    if len(names) >= 3 and is_whole_series(names):
        return f"{names[0]}…{names[-1]}"
    return ", ".join(names[:-1]) + " and " + names[-1]


def what_there_is(pictures: list[str], clips: list[str]) -> str:
    """The video's pictures and clips in words, for a refusal: "the pictures are img1…img8; there are no clips"."""
    if pictures:
        picture_words = f"the pictures are {names_in_words(pictures)}"
    else:
        picture_words = "there are no pictures"
    if clips:
        clip_words = f"the clips are {names_in_words(clips)}"
    else:
        clip_words = "there are no clips"
    return f"{picture_words}; {clip_words}"


def unknown_name_problem(body: str, assets_script: str) -> str | None:
    """Decides whether the page draws a picture or clip the video doesn't have, read from the page's text before
    anything is drawn: the first such name as words to fix, or None. With img1…img8 stapled, s.photo("img9") ->
    "There is no img9: the pictures are img1…img8; there are no clips. Use only those names."; with nothing stapled,
    s.photo("img1") -> "There is no img1: this video has no pictures or clips, so remove s.photo("img1") …";
    s.photo("img2") with img2 stapled, or s.photo(name) -> None (a name in a variable is the kit's to tell)."""
    pictures, clips = stapled_names(assets_script)
    known = set(pictures) | set(clips)
    for match in NAME_USED.finditer(body):
        helper = match.group(1)
        name = match.group(3).strip()
        if name in known:
            continue
        if not known:
            return (f'There is no {name}: this video has no pictures or clips, so remove s.{helper}("{name}") and '
                    "draw that moment another way (shapes, text, formulas, 3D or the map).")
        return f"There is no {name}: {what_there_is(pictures, clips)}. Use only those names."
    return None


async def submission_problem(narration, body: str, browser, assets_script: str = "") -> str | None:
    """Decides whether a video can be accepted: the first problem as words to fix, or None. In this order: a page over
    300 KB -> the limit; narration that isn't a list of strings -> NOT_A_LIST; a narration problem (["Hi.", "  "] ->
    scene 2 has no words); a picture or clip the video doesn't have (s.photo("img9") with img1…img8 -> "There is no
    img9: …", see unknown_name_problem); until here nothing is drawn. Then the page drawn in the browser (a draw that
    throws -> "The page threw in scene 2 at t = 1.2 s: …"; a frame that never finishes -> the HANG wording). The
    worked example with two narration strings -> None. The page is drawn with the video's pictures and clips
    (`assets_script`), so s.photo("img1") draws when img1 was gathered. A browser that fails in another way (it won't
    start) is not the page's problem: its BrowserError goes up to the check."""
    problem = page_problem(body)
    if problem:
        return problem
    if not is_list_of_strings(narration):
        return NOT_A_LIST
    problem = narration_problem(narration)
    if problem:
        return problem
    problem = unknown_name_problem(body, assets_script)
    if problem:
        return problem
    try:
        return await video_page.check(body, narration, browser, assets_script)
    except BrowserTimeout as e:
        return HANG + str(e)


def tools_for(desk: Desk, browser, assets_script: str = "") -> list:
    """The writer's one tool, submit_video (title, narration, page), built by the shared harness on `desk`. Its check
    keeps the page under desk.pages first, then judges it (submission_problem, drawn with the video's pictures and
    clips, `assets_script`); a browser that fails is no refusal:
    the job ends with the browser's own words. Accepting makes the Written video, the title falling back to the
    topic."""

    async def check(fields: dict) -> str | None:
        body = text_or_empty(fields["page"])
        keep_page(desk.pages, body)
        narration = narration_as_given(fields["narration"])
        try:
            return await submission_problem(narration, body, browser, assets_script)
        except BrowserError as e:
            words = str(e).strip()
            if not words:
                words = BROWSER_FAILED
            raise harness.CantCheck(words) from e

    def accept(fields: dict) -> Written:
        title = harness.title_given(fields["title"], desk.topic)
        narration = list(narration_as_given(fields["narration"]))
        return Written(title=title, narration=narration, body=text_or_empty(fields["page"]))

    return [harness.submit_tool(desk, "submit_video", SUBMIT_DOC, SUBMIT_FIELDS, check, accept)]


async def write(topic: str, minutes: int, brief: str, folder: Path, turn, browser, listing: str = "",
                assets_script: str = "") -> Written:
    """Writes the video in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)` is
    runner.focused_turn in Odie, `browser` the one page.check draws in (render_browser()), `listing` the pictures and
    clips the writer may use, by name (see prompt_for), and `assets_script` those same pictures and clips stapled
    (odie.video.assets.staple), so the check draws them. Every submitted page is kept under folder/pages. Returns the
    accepted video; raises WriterFailed when there's none, with the video's words (LINES), or the harness's time-limit
    line (see odie.making.writer.write)."""
    desk = Desk(topic=topic, pages=folder / "pages")
    [tool] = tools_for(desk, browser, assets_script)
    prompt = prompt_for(topic, minutes, brief, listing)
    return await harness.write(desk, prompt, INSTRUCTION, tool, LINES, turn)
