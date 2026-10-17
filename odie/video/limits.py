"""What an explainer video may be: the narration's and the page's limits, checked before anything is drawn. Shared by
the video writer's tools and the explainer-video skill's tool."""
from odie.video import beats, timeline

SCENE_CHARACTERS = 4000  # the most narration one scene may have (one piece of speech)
MAX_SCENES = 40  # the most scenes a video may have (a 6-minute video needs far fewer)
MAX_PAGE_KB = 300  # the largest page body, in kilobytes (the worked example is about 3)


def narration_problem(narration: list[str]) -> str | None:
    """Decides whether the narration can be spoken as it is, before anything is drawn: the first problem as words to
    act on, or None. In this order: [] -> no narration; 41 strings -> over the 40-scene limit; ["Hi.", "  "] ->
    scene 2 has no words; ["ok.", 4,001 characters] -> scene 2 is over the 4,000-character limit; seven scenes of 140
    words (7 minutes of speech) -> over 6 minutes (the "|" beat marks are not words); then the beats (beats.problem):
    ["Hi.", "A || B"] -> scene 2 has an empty phrase; ["Hi."] or ["A | B"] -> None."""
    if not narration:
        return "There's no narration: give one string of speech per scene, in order."
    if len(narration) > MAX_SCENES:
        return (f"There are {len(narration)} scenes; a video can have at most {MAX_SCENES}. Join some scenes "
                "(and their narration) together.")

    for number, text in enumerate(narration, start=1):
        if not text.strip():
            return f"There's no narration for scene {number}: every scene needs words to speak."
        if len(text) > SCENE_CHARACTERS:
            return (f"The narration of scene {number} is {len(text):,} characters; one scene can have at most "
                    f"{SCENE_CHARACTERS:,}. Split it into two scenes (and two scenes on the page) or shorten it.")

    minutes = timeline.spoken_minutes(beats.spoken(narration))
    if minutes > timeline.MAX_MINUTES:
        return (f"The narration is about {minutes:.1f} minutes of speech; a video can be at most "
                f"{timeline.MAX_MINUTES} minutes. Shorten it (about {timeline.WORDS_PER_MINUTE} words a minute).")
    return beats.problem(narration)


def page_problem(page: str) -> str | None:
    """Decides whether the page is small enough to check and render: a body over 300 KB (in UTF-8) -> the limit, as
    words to act on; the worked example's 3 KB, or exactly 300,000 bytes -> None."""
    size = len(page.encode("utf-8"))
    if size > MAX_PAGE_KB * 1000:
        return (f"The page is {size / 1000:,.0f} KB; a page can be at most {MAX_PAGE_KB} KB. Draw with code (loops, "
                "helpers) instead of long lists of data or pasted content.")
    return None
