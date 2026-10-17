"""A video page, put together: the kit (KaTeX and its fonts, three.js, video.js) and the scene timings inlined ahead
of the model's page, so the sealed render tab needs nothing from the network. Also checks a page before the render."""
import base64
import functools
import json
import re
from pathlib import Path

from odie.browser.engine import BrowserError, BrowserTimeout
from odie.video import beats, timeline

KIT = Path(__file__).parent / "kit"

# The page around the kit: a black page with no margin; video.js puts its 1920x1080 stage at the top left.
BASE_STYLE = "html, body { margin: 0; background: #000; overflow: hidden; width: 1920px; height: 1080px; }"

# A src= or href= attribute, or a CSS url(), that points at http(s) or a protocol-relative "//" address.
NETWORK_LINK = re.compile(r"""(?:\b(?:src|href)\s*=\s*["']?|\burl\(\s*["']?)\s*((?:https?:)?//[^"'\s)>]*)""",
                          re.IGNORECASE)

# The .woff and .ttf alternatives KaTeX's CSS lists after each .woff2 (only the .woff2 files ship).
OTHER_FONT_FORMATS = re.compile(r',\s*url\(fonts/[^)]+\.(?:woff|ttf)\)\s*format\("[^"]*"\)')
WOFF2_URL = re.compile(r"url\(fonts/([^)]+\.woff2)\)")


def inline_fonts(css: str, fonts: Path) -> str:
    """KaTeX's CSS with each font carried inside it, because the sealed tab can't fetch fonts/ files: every
    url(fonts/X.woff2) becomes a base64 data URI and the .woff/.ttf alternatives (not shipped) are dropped.
    'src:url(fonts/A.woff2) format("woff2"),url(fonts/A.woff) format("woff")'
    -> 'src:url(data:font/woff2;base64,...) format("woff2")'."""
    css = OTHER_FONT_FORMATS.sub("", css)

    def as_data_uri(match: re.Match) -> str:
        data = (fonts / match.group(1)).read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return f"url(data:font/woff2;base64,{encoded})"

    return WOFF2_URL.sub(as_data_uri, css)


@functools.cache
def _kit() -> dict[str, str]:
    """The kit's files, read once: KaTeX's CSS (fonts inlined), three.js, KaTeX and video.js."""
    return {
        "katex_css": inline_fonts((KIT / "katex.min.css").read_text(), KIT / "fonts"),
        "three": (KIT / "three.min.js").read_text(),
        "katex": (KIT / "katex.min.js").read_text(),
        "video": (KIT / "video.js").read_text(),
    }


def check_offline(body: str) -> None:
    """Refuses a page that loads anything from the network (the sealed tab would refuse the request anyway; this
    says why). '<script src="https://cdn.example/three.js">' -> ValueError; 'https://arxiv.org' in a caption -> fine."""
    match = NETWORK_LINK.search(body)
    if match:
        address = match.group(1)
        raise ValueError(f"The page loads {address} from the network, but a video page can't: everything ships with "
                         f"the kit (three.js as THREE, KaTeX as katex, video.js as Video); remove {address}.")


def assemble(body: str, timings: dict, assets_script: str = "") -> str:
    """The whole HTML document for a video: KaTeX's CSS, three.js, KaTeX, video.js, then `window.__timings`
    ({"starts": [...], "lengths": [...], "beats": [[...], ...]}, in seconds, passed through as given), then the
    video's pictures and clips (`assets_script`, odie.video.assets.staple's `<script>Video.assets({...})</script>`,
    when there are any), then `body` (the model's markup and script), in that order."""
    check_offline(body)
    kit = _kit()
    head = [
        '<!doctype html><html><head><meta charset="utf-8"><title>video</title>',
        f"<style>{kit['katex_css']}</style>",
        f"<style>{BASE_STYLE}</style>",
        f"<script>{kit['three']}</script>",
        f"<script>{kit['katex']}</script>",
        f"<script>{kit['video']}</script>",
        f"<script>window.__timings = {json.dumps(timings)};</script>",
    ]
    if assets_script:
        head.append(assets_script)
    head.append("</head><body>")
    return "\n".join(head) + "\n" + body + "\n</body></html>\n"


MIN_SCENE_SECONDS = 2.0  # a scene with only a few words is still on screen this long
PROBE_EDGE = 0.05        # seconds after a scene's first moment, where it is first probed
PROBES_PER_SCENE = 3     # just after the start, the middle, the very end


def estimated_beats(text: str, length: float) -> list[float]:
    """A scene's beat starts guessed from its phrases' words, each phrase taking its share of the scene's length:
    "seven words | twenty-one words" in a 12 s scene -> [0.0, 3.0] (the second phrase starts 7/28 of the way in);
    no marks -> [0.0]."""
    word_counts = [len(phrase.split()) for phrase in beats.phrases(text)]
    total = max(1, sum(word_counts))
    starts = []
    words_before = 0
    for count in word_counts:
        starts.append(round(length * words_before / total, 3))
        words_before += count
    return starts


def estimated_timings(narration: list[str]) -> dict:
    """Scene timings guessed from the words alone (the real ones come from the recorded voice later): each scene lasts
    its words at WORDS_PER_MINUTE, but at least 2 s. At 140 words a minute that is 2.33 words a second, so
    ["one two three", 70 words] -> lengths [2.0, 30.0] (3 words would be 1.29 s, raised to 2.0),
    starts [0.0, 2.5] (scene 2 begins after scene 1's 2 s and the 0.5 s breath) and beats [[0.0], [0.0]]. A "|"
    mark is not a word; it gives the scene one more beat (estimated_beats), as the real narration will."""
    words_per_second = timeline.WORDS_PER_MINUTE / 60
    lengths = []
    scene_beats = []
    for text, said in zip(narration, beats.spoken(narration)):
        seconds = len(said.split()) / words_per_second
        length = round(max(MIN_SCENE_SECONDS, seconds), 3)
        lengths.append(length)
        scene_beats.append(estimated_beats(text, length))
    starts, _total = timeline.scene_starts(lengths)
    return {"starts": starts, "lengths": lengths, "beats": scene_beats}


def probe_times(timings: dict) -> list[float]:
    """Three moments in every scene to draw once: just after its start, its middle, and exactly its end (the held end
    state and every breath frame are drawn at t = length, where `items[Math.floor(p * n)]` runs one past the end).
    Scene at 4.5 s lasting 2 s -> [4.55, 5.5, 6.5]. Scene k's times are entries PROBES_PER_SCENE*k onward."""
    times = []
    for start, length in zip(timings["starts"], timings["lengths"]):
        times.append(round(start + PROBE_EDGE, 3))
        times.append(round(start + length / 2, 3))
        times.append(round(start + length, 3))
    return times


def first_problem(scene_count: int | None, narration_count: int, load_errors: list[str],
                  draw_errors: list[tuple[int, float, str]]) -> str | None:
    """Decides which single problem the model hears about, as one plain paragraph (fixing one at a time is clearer than
    a list, and a first fault often causes the later ones). The order is the order they would bite:
    page never called Video.scenes (scene_count None) -> "never called Video.scenes", and if the page also raised
    errors while loading, the first of them instead (a typo in the script is the real reason);
    2 scenes, 1 narration part -> the count mismatch; the page's own error while loading (e.g. in a scene's setup);
    then the earliest draw error, given as (scene number, seconds into that scene, which is draw's t, text):
    [(2, 1.95, "boom")] -> "The page threw in scene 2 at t = 1.95 s: boom". Nothing wrong -> None."""
    if scene_count is None:
        if load_errors:
            return f"The page failed while loading, before it called Video.scenes(...): {load_errors[0]}"
        return "The page never called Video.scenes(...): put all scenes in one Video.scenes([...]) call."
    if scene_count != narration_count:
        return (f"The page has {scene_count} scenes but there are {narration_count} narration parts: "
                "one narration per scene.")
    if load_errors:
        return f"The page raised an error while loading: {load_errors[0]}"
    if draw_errors:
        scene, seconds, text = draw_errors[0]
        return f"The page threw in scene {scene} at t = {seconds} s: {text}"
    return None


async def check(body: str, narration: list[str], browser, assets_script: str = "") -> str | None:
    """Loads the page in a sealed 1920x1080 tab with estimated timings and the video's pictures and clips
    (`assets_script`, as the render will have them) and draws three moments of every scene, so the chat turn hears
    about a broken page now and not after minutes of rendering. None when the page is fine, else the first problem as
    a paragraph to act on (see first_problem). A page that reaches for the network is a problem too."""
    timings = estimated_timings(narration)
    try:
        html = assemble(body, timings, assets_script)
    except ValueError as e:
        return str(e)
    async with browser.sealed_page(html, 1920, 1080) as tab:
        load_errors = list(tab.errors)
        scene_count = await tab.eval("window.__sceneCount === undefined ? null : window.__sceneCount")
        problem = first_problem(scene_count, len(narration), load_errors, [])
        if problem:
            return problem
        draw_errors = []
        for number, seconds in enumerate(probe_times(timings)):
            error = await _draw_error(tab, seconds)
            if error:
                scene_index = number // PROBES_PER_SCENE
                t = round(seconds - timings["starts"][scene_index], 3)  # draw's t: seconds into the scene
                draw_errors.append((scene_index + 1, t, error))
                break
        return first_problem(scene_count, len(narration), load_errors, draw_errors)


async def _draw_error(tab, seconds: float) -> str | None:
    """Draws the frame at `seconds`; the page's error text if it threw, else None. An exception thrown by the evaluated
    expression comes back as the exception eval raises and (measured) not in tab.errors; should a browser record it
    in both, the first new line in tab.errors is used so it is told once. Not a decision function: it reports."""
    before = len(tab.errors)
    raised = None
    try:
        await tab.eval(f"__frame({seconds})")
    except BrowserTimeout:
        raise  # a frame that never finishes isn't an error the page threw: make_video tells it as a hang
    except BrowserError as e:
        raised = str(e)
    new_errors = tab.errors[before:]
    if new_errors:
        return new_errors[0]
    return raised
