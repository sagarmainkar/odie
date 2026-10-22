"""The video writer: one focused model turn, in the background, that writes an explainer video's narration and page.

It runs on the shared writer harness (odie.making.writer). It sees only writer.md (the page contract, the kit, the
worked example, the style) and one tool, submit_video, which takes the title, the narration and the whole page at
once. Every page sent is kept in the job's folder (pages/page-1.html, page-2.html, …), then checked: its size, the
narration, and the page drawn in a browser. A problem goes back to the writer to fix. An accepted video, a third
refusal or a browser that fails ends the turn there and then, with no more model calls. A writer that stops without
any of those is nudged once, in the same session. The turn ends with the accepted video (Written) or WriterFailed.
The sound cues the page places (Video.sounds([...])) are read back by the page check, judged against the narration
(odie.video.sounds.cue_problem) and kept on the accepted video; the submit tool itself takes no cues. Cues that
don't fit refuse a page once; after that, the ones that don't fit are dropped (and logged) and the page is accepted,
so a mis-named sound never fails a video."""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from odie.browser.engine import BrowserError, BrowserTimeout
from odie.making import writer as harness
from odie.making.chat import text_or_empty
from odie.video import brand, sounds, timed, timeline
from odie.video import page as video_page
from odie.video.limits import narration_problem, page_problem

INSTRUCTION = Path(__file__).with_name("writer.md").read_text(encoding="utf-8")
VERTICAL_RULES = Path(__file__).with_name("writer-vertical.md").read_text(encoding="utf-8")
TIMED_RULES = Path(__file__).with_name("writer-timed.md").read_text(encoding="utf-8")
log = logging.getLogger("odie.video")


def timed_rules(seconds: float) -> str:
    """writer-timed.md for a segment of `seconds`: its seconds and its word budget written in (odie.video.timed):
    60 -> "… a timed segment of 60 seconds …", "about 140 words (115 to 170)"."""
    words, fewest, most = timed.word_budget(seconds)
    rules = TIMED_RULES.replace("__SECONDS__", f"{seconds:.0f}").replace("__WORDS__", str(words))
    return rules.replace("__FEWEST__", str(fewest)).replace("__MOST__", str(most))


def instruction_for(aspect: str, timed_seconds: float | None = None, kit: brand.Kit | None = None) -> str:
    """The writer's instruction for the video's aspect, its timed segment and its brand kit: writer.md for a landscape
    video (the guide is written for its 1920 x 1080 stage); for a vertical one, writer.md and then writer-vertical.md
    (the 1080 x 1920 stage, the safe area, one idea a screen); a video with a timed segment (odie.video.timed) then
    gets its rules (timed_rules: mark the segment, its words, the segment clock s.left()); a video with a brand kit
    then gets the kit's functions and rules last (odie.video.brand.writer_rules), so they win over the general guide.
    "landscape" -> INSTRUCTION; "vertical" -> INSTRUCTION + the vertical rules; ("vertical", timed_seconds=60) ->
    those + the 60-second segment's rules; with a kit -> those + the kit's."""
    instruction = INSTRUCTION
    if aspect == "vertical":
        instruction = instruction.rstrip() + "\n\n" + VERTICAL_RULES
    if timed_seconds:
        instruction = instruction.rstrip() + "\n\n" + timed_rules(timed_seconds)
    if kit is not None:
        instruction = instruction.rstrip() + "\n\n" + brand.writer_rules(kit)
    return instruction

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
BRAND_DOC = ("\nbrand: the brand kit's words for its bookends, by name, as its rules list them "
             '({"name": "one short line"}).')


def submit_fields(kit: brand.Kit | None) -> dict:
    """submit_video's arguments: title, narration and page; and brand (the bookends' words) when the video's kit has
    words to give. No kit, or a kit without vars -> the three; a kit with vars -> the three and brand."""
    fields = dict(SUBMIT_FIELDS)
    if kit is not None and kit.vars:
        fields["brand"] = dict[str, str]
    return fields


def submit_doc(kit: brand.Kit | None) -> str:
    """What the writer reads about submit_video: SUBMIT_DOC, and the brand argument when it has one (submit_fields)."""
    if kit is not None and kit.vars:
        return SUBMIT_DOC + BRAND_DOC
    return SUBMIT_DOC


@dataclass
class Written:
    """The accepted video: its title, one string of narration per scene, the page body that draws them, the sound
    cues the page placed (Video.sounds, as odie.video.page.CheckResult gives them; [] when it placed none), and its
    timed segment's first and last scene, 0-based ((1, 2); None for a video without one)."""
    title: str
    narration: list[str]
    body: str
    cues: list[dict] = field(default_factory=list)
    segment: tuple[int, int] | None = None
    brand_vars: dict[str, str] = field(default_factory=dict)  # the brand kit's bookend words ({} without a kit)


@dataclass(kw_only=True)
class Desk(harness.Desk):
    """The shared desk (odie.making.writer.Desk), plus where this video's submitted pages are kept, the sound cues and
    the timed segment an accepted page keeps (set by every check: [] and None when it refused), and how many pages
    were refused for their cues."""
    pages: Path
    cues: list[dict] = field(default_factory=list)
    segment: tuple[int, int] | None = None
    cue_refusals: int = 0
    kit: brand.Kit | None = None  # the video's brand kit, whose sounds join the cues' names


@dataclass
class Judged:
    """A submission judged (checked_submission): the page's first problem (None when the page is fine), the cues'
    first problem (odie.video.sounds.cue_problem; None when they fit, and not looked for while the page has a
    problem), the cues the page placed, and its timed segment's scenes (None without one)."""
    problem: str | None
    cue_problem: str | None = None
    cues: list[dict] = field(default_factory=list)
    segment: tuple[int, int] | None = None


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


async def checked_submission(narration, body: str, browser, assets_script: str = "",
                             size: tuple[int, int] = timeline.LANDSCAPE, timed_seconds: float | None = None,
                             kit: brand.Kit | None = None, kit_vars=None) -> Judged:
    """Decides whether a video can be accepted: the page's first problem as words to fix, or None, then the sound
    cues' first problem apart from it (the tool refuses on cues only once; see cues_answer), with the cues the page
    placed. In this order: a page over 300 KB -> the limit; narration that isn't a list of strings ->
    NOT_A_LIST; a narration problem (["Hi.", "  "] -> scene 2 has no words); a picture or clip the video doesn't have
    (s.photo("img9") with img1…img8 -> "There is no img9: …", see unknown_name_problem); until here nothing is drawn.
    Then the page drawn in the browser (a draw that throws -> "The page threw in scene 2 at t = 1.2 s: …"; a frame
    that never finishes -> the HANG wording; Video.sounds given something other than a list -> the kit's words). Then
    the sound cues it placed, against the narration, as cue_problem, shape included (a cue on "wooosh" ->
    "Video.sounds: cue 1: there is no sound called 'wooosh'; …"; {at: "1.5", …} -> "Video.sounds: cue 1 has at
    '1.5'; …", see odie.video.sounds.cue_problem). The worked example with two narration strings -> no
    problem and no cues. The page is drawn with the video's pictures and clips (`assets_script`), so s.photo("img1")
    draws when img1 was gathered, at the video's `size` (1080 x 1920 for a vertical video). A video with a timed
    segment of `timed_seconds` must mark it in Video.scenes (the page check says how), and the marked scenes must be
    about that many seconds of words (odie.video.timed.words_problem: 30 words for 60 s -> what to write); its page is
    drawn with the segment clock running. Without one, the marks are ignored. A browser that fails in another way (it
    won't start) is not the page's problem: its BrowserError goes up to the check. A video with a brand kit (`kit`,
    with the bookends' words the writer gave, `kit_vars`) is also refused for a page that changes Brand
    (brand.reassign_problem) or words that are missing (brand.vars_problem), before anything is drawn, and is drawn
    with the kit in (brand.check: a scene painting over the kit's background, or moves that can't play, are refused
    too); its sounds join the cues' names. A kit that breaks while drawing is brand.KitProblem, up to the check."""
    problem = page_problem(body)
    if problem:
        return Judged(problem=problem)
    if not is_list_of_strings(narration):
        return Judged(problem=NOT_A_LIST)
    problem = narration_problem(narration)
    if problem:
        return Judged(problem=problem)
    problem = unknown_name_problem(body, assets_script)
    if problem:
        return Judged(problem=problem)
    kit_names = ()
    if kit is not None:
        kit_names = tuple(kit.sounds)
        problem = brand.reassign_problem(body)
        if problem:
            return Judged(problem=problem)
        problem = brand.vars_problem(kit, kit_vars)
        if problem:
            return Judged(problem=problem)
    try:
        if kit is not None:
            branded = brand.Branded(kit, dict(kit_vars or {}))
            drawn = await brand.check(body, narration, browser, branded, assets_script, size=size,
                                      timed_seconds=timed_seconds)
        else:
            drawn = await video_page.check_with_cues(body, narration, browser, assets_script, size=size,
                                                     timed_seconds=timed_seconds)
    except BrowserTimeout as e:
        return Judged(problem=HANG + str(e))
    if drawn.problem:
        return Judged(problem=drawn.problem)
    segment = None
    if timed_seconds and drawn.segment is not None:
        segment = drawn.segment
        first, last = segment
        problem = timed.words_problem(narration, first, last, timed_seconds)
        if problem:
            return Judged(problem=problem)
    cue_problem = sounds.cue_problem(drawn.cues, narration, kit_names)
    return Judged(problem=None, cue_problem=cue_problem, cues=drawn.cues, segment=segment)


async def submission_problem(narration, body: str, browser, assets_script: str = "") -> str | None:
    """Decides whether a video can be accepted, as checked_submission does, telling a page problem and a cue problem
    alike: the first problem as words to fix ("The page threw in scene 2 at t = 1.2 s: …", or "Video.sounds: cue 1:
    …"), or None (the worked example)."""
    judged = await checked_submission(narration, body, browser, assets_script)
    if judged.problem:
        return judged.problem
    return judged.cue_problem


def refuses_for_cues(desk: Desk) -> bool:
    """Decides whether cues that don't fit refuse the page, or are dropped. They refuse it only when no page was refused
    for its cues yet and this refusal wouldn't be the writer's last (the harness stops at MAX_REJECTIONS refusals);
    otherwise the cues that don't fit are dropped and the page is accepted, so a sound never fails the video. No
    refusals yet -> True (the writer hears the words and can fix them); one cue refusal already -> False; two page
    refusals already, none for cues -> False (a third refusal would end the writing)."""
    no_cue_refusal_yet = desk.cue_refusals == 0
    tries_left_after_this = desk.rejected < harness.MAX_REJECTIONS - 1
    return no_cue_refusal_yet and tries_left_after_this


def cues_answer(desk: Desk, judged: Judged, narration: list[str]) -> str | None:
    """The tool's answer for a page that drew fine, from its cues, setting desk.cues to what an accepted page keeps.
    Cues that fit -> None, all kept. The first time cues don't fit, with tries to spare -> their problem (a refusal),
    desk.cues []. Any later time, or on the writer's last try (see refuses_for_cues) -> None, desk.cues only the cues
    that pass (odie.video.sounds.good_cues), the drop logged: one good cue and one on "wooosh" -> accepted with the
    good one."""
    if judged.cue_problem is None:
        desk.cues = judged.cues
        return None
    if refuses_for_cues(desk):
        desk.cue_refusals += 1
        desk.cues = []
        return judged.cue_problem
    kit_names = ()
    if desk.kit is not None:
        kit_names = tuple(desk.kit.sounds)
    kept = sounds.good_cues(judged.cues, narration, kit_names)
    desk.cues = kept
    log.warning("video %r: kept %d of %d sound cues after one refusal; dropped the rest: %s", desk.topic, len(kept),
                len(judged.cues), judged.cue_problem)
    return None


def tools_for(desk: Desk, browser, assets_script: str = "", size: tuple[int, int] = timeline.LANDSCAPE,
              timed_seconds: float | None = None) -> list:
    """The writer's one tool, submit_video (title, narration, page), built by the shared harness on `desk`. Its check
    keeps the page under desk.pages first, then judges it (checked_submission, drawn with the video's pictures and
    clips, `assets_script`, at the video's `size`, with a timed segment of `timed_seconds` when there is one); a page
    that drew fine is answered from its cues (cues_answer: they refuse it at most once, then the ones that don't fit
    are dropped), which puts the cues and the timed segment's scenes to keep on the desk; a browser that fails is no
    refusal: the job ends with the browser's own words, and so does a brand kit that breaks (desk.kit: its
    words). Accepting makes the Written video with those cues, that segment and the kit's words (the harness accepts
    right after the check that passed), the title falling back to the topic."""

    async def check(fields: dict) -> str | None:
        body = text_or_empty(fields["page"])
        keep_page(desk.pages, body)
        narration = narration_as_given(fields["narration"])
        kit_vars = brand.vars_as_given(fields.get("brand"))
        desk.cues = []
        desk.segment = None
        try:
            judged = await checked_submission(narration, body, browser, assets_script, size=size,
                                              timed_seconds=timed_seconds, kit=desk.kit, kit_vars=kit_vars)
        except BrowserError as e:
            words = str(e).strip()
            if not words:
                words = BROWSER_FAILED
            raise harness.CantCheck(words) from e
        except brand.KitProblem as e:
            raise harness.CantCheck(str(e)) from e
        if judged.problem:
            return judged.problem
        desk.segment = judged.segment
        return cues_answer(desk, judged, narration)

    def accept(fields: dict) -> Written:
        title = harness.title_given(fields["title"], desk.topic)
        narration = list(narration_as_given(fields["narration"]))
        cues = list(desk.cues)
        kit_vars = {}
        if desk.kit is not None and desk.kit.vars:
            kit_vars = dict(brand.vars_as_given(fields.get("brand")))
        return Written(title=title, narration=narration, body=text_or_empty(fields["page"]), cues=cues,
                       segment=desk.segment, brand_vars=kit_vars)

    fields = submit_fields(desk.kit)
    return [harness.submit_tool(desk, "submit_video", submit_doc(desk.kit), fields, check, accept)]


async def write(topic: str, minutes: int, brief: str, folder: Path, turn, browser, listing: str = "",
                assets_script: str = "", aspect: str = "landscape", timed_seconds: float | None = None,
                kit: brand.Kit | None = None) -> Written:
    """Writes the video in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)` is
    runner.focused_turn in Odie, `browser` the one page.check draws in (render_browser()), `listing` the pictures and
    clips the writer may use, by name (see prompt_for), and `assets_script` those same pictures and clips stapled
    (odie.video.assets.staple), so the check draws them. `aspect` ("landscape" or "vertical") picks the instruction
    (instruction_for) and the size the page is checked at; `timed_seconds` (odie.video.timed) adds the timed segment's
    rules, and the page must mark the segment and is checked with its clock; a brand `kit` adds its rules, the brand
    argument when it has words to give, and its checks (checked_submission). Every submitted page is kept under
    folder/pages. Returns the accepted video; raises WriterFailed when there's none, with the video's words (LINES), or
    the harness's time-limit line (see odie.making.writer.write)."""
    desk = Desk(topic=topic, pages=folder / "pages", kit=kit)
    size = timeline.size_of(aspect)
    [tool] = tools_for(desk, browser, assets_script, size=size, timed_seconds=timed_seconds)
    prompt = prompt_for(topic, minutes, brief, listing)
    return await harness.write(desk, prompt, instruction_for(aspect, timed_seconds, kit), tool, LINES, turn)
