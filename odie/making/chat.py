"""What the chat tools that start a background job share (make_video, make_podcast and make_deck): reading
the model's arguments as it sends them, the checks every kind makes in its own words and limits, a folder of its own
for every job, and the reply that says how long it takes."""
import re
from pathlib import Path

from odie.agent.tools.files import safe_name

MAX_BRIEF_CHARACTERS = 6000
AFTER_THE_ESTIMATE = ("It'll appear in this chat, with a ping on the phone, as soon as it's ready. Tell the user that "
                      "in one or two lines, and that they can keep chatting meanwhile.")


def text_or_empty(value) -> str:
    """A text argument the model may have sent as null: None -> ""; "How attention works" -> the same."""
    if value is None:
        return ""
    return value


def slug_of(title: str, fallback: str) -> str:
    """The title as a folder name: lower case, words joined by hyphens, only a-z, 0-9 and hyphens; with nothing left,
    the fallback (the kind's word). "Speculative decoding" -> "speculative-decoding"; "TCP/IP, explained" ->
    "tcp-ip-explained"; "!!!" with fallback "video" -> "video"."""
    no_slashes = title.replace("/", " ").replace("\\", " ")  # safe_name would keep only what follows a slash
    lowered = safe_name(no_slashes).lower()
    hyphenated = re.sub(r"\s+", "-", lowered)
    kept = re.sub(r"[^a-z0-9-]", "", hyphenated)
    slug = re.sub(r"-{2,}", "-", kept).strip("-")
    if not slug:
        return fallback
    return slug


def free_folder(root: Path, slug: str) -> Path:
    """The folder for a new job: root/slug, or root/slug-2, root/slug-3 … when earlier jobs have those, so an earlier
    job's folder is never reused or overwritten. "attention" with videos/attention there -> attention-2."""
    folder = root / slug
    number = 2
    while folder.exists():
        folder = root / f"{slug}-{number}"
        number += 1
    return folder


def minutes_as_given(minutes, default: int):
    """The length the model meant, before it is checked. Some models send numbers as text or leave an optional
    argument null: "2" or " 3 " -> 2 or 3; None -> the default. Anything else is passed on unchanged for
    minutes_problem to judge: 4 -> 4; "two", "2.5" or "²" (a digit to str.isdigit, but not a number int() reads) ->
    the same text, refused there as text."""
    if minutes is None:
        return default
    if isinstance(minutes, str) and minutes.strip().isdecimal():
        return int(minutes.strip())
    return minutes


def minutes_problem(minutes, lowest: int, highest: int, word: str, default: int) -> str | None:
    """Decides whether the length can be made: a whole number of minutes from `lowest` to `highest` -> None; outside
    it or not whole -> the range, as words to act on. A video (1 to 6, else 2): 3 -> None; 7 -> "minutes is the video's
    length in whole minutes, from 1 to 6 (the user's length, else 2), not 7."; "two" -> "… got the text 'two'.".
    True/False are not lengths, though Python counts them as numbers."""
    is_whole = isinstance(minutes, int) and not isinstance(minutes, bool)
    if is_whole and lowest <= minutes <= highest:
        return None
    given = f"not {minutes}"
    if isinstance(minutes, str):
        given = f"got the text '{minutes}'"
    return (f"minutes is the {word}'s length in whole minutes, from {lowest} to {highest} (the user's length, else "
            f"{default}), {given}.")


def brief_problem(brief: str, word: str, limit: int = MAX_BRIEF_CHARACTERS) -> str | None:
    """Decides whether the brief is short enough for the writer: up to `limit` characters (6,000 unless the kind
    says) -> None; one more -> the limit, as words to act on, naming the kind. 6,001 for a deck -> "The brief is 6,001
    characters; it can be at most 6,000. Keep only what the deck needs: …"; the video allows 20,000."""
    if len(brief) <= limit:
        return None
    return (f"The brief is {len(brief):,} characters; it can be at most {limit:,}. Keep only what the "
            f"{word} needs: who it's for, the key points in order, the examples and the facts it must use.")


def reply(place: int, low: int, high: int, doing: str) -> str:
    """What the model is told once the job is in line: about low–high minutes, and `doing` (the kind's steps) when it
    is made now. Place 1 (nothing else being made), 3–5, "writing the script and the animation, then drawing it" ->
    "Making it now: about 3–5 minutes (writing the script and the animation, then drawing it). …"; place 2 (one being
    made already) -> "It's number 2 in line, about 3–5 minutes after the one before. …". Either way it says the result
    comes to this chat with a ping, and that the chat stays free."""
    if place <= 1:
        return f"Making it now: about {low}–{high} minutes ({doing}). {AFTER_THE_ESTIMATE}"
    return f"It's number {place} in line, about {low}–{high} minutes after the one before. {AFTER_THE_ESTIMATE}"
