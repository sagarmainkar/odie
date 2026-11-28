"""Libra: the user's own voice server (Libra-TTS, an OpenAI-style /v1/audio/speech on this Mac or another on the home
network), and the voice markup the chat model writes when Libra is the voice.

The markup: a reply may open with one tone marker, <tone:wry>, and carry a few sound tags where they happen, <laugh>,
<sigh>. Nobody sees them: every screen hides them (web drawnText, the Mac's reply parts, pushes, the terminal).
Libra hears them: the tone becomes its style and the tags are performed. Any other voice gets them stripped. Only
these known markers count, so any other <something> a reply has stays as it is."""
from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

import httpx

DEFAULT_URL = "http://127.0.0.1:8794"
DEFAULT_VOICE = "nina"
VOICES = [
    {"id": "nina", "label": "Nina", "group": "female"},
    {"id": "sofia", "label": "Sofia", "group": "female"},
    {"id": "aliya", "label": "Aliya", "group": "female"},
    {"id": "maya", "label": "Maya", "group": "female"},
    {"id": "omar", "label": "Omar", "group": "male"},
    {"id": "jon", "label": "Jon", "group": "male"},
    {"id": "bob", "label": "Bob", "group": "male"},
    {"id": "sam", "label": "Sam", "group": "male"},
]
TONES = ["warm", "cheerful", "excited", "sad", "frightened", "calm", "serious", "wry", "tender", "whispering",
         "dramatic", "documentary"]
TAGS = ["laugh", "chuckle", "giggle", "snicker", "sigh", "gasp", "breath", "heavy breath", "exhales", "phew",
        "short pause", "long pause", "cough", "throat-clearing", "sneeze", "yawn", "sob", "cry", "whimper", "groan",
        "tsk", "shout"]
# the tags the chat model is offered: the ones that suit a conversation (all of TAGS are still hidden and spoken)
CHAT_TAGS = ["laugh", "chuckle", "sigh", "gasp", "exhales", "phew", "short pause", "long pause", "tsk", "groan"]

_TONE_PATTERN = r"<tone:(" + "|".join(TONES) + r")>"
_TAG_PATTERN = r"<(?:" + "|".join(re.escape(t) for t in TAGS) + r")>"
TONE_MARKER = re.compile(_TONE_PATTERN, re.IGNORECASE)
TAG_MARKER = re.compile(_TAG_PATTERN, re.IGNORECASE)
ANY_MARKER = re.compile(f"{_TONE_PATTERN}|{_TAG_PATTERN}", re.IGNORECASE)
_MARKER_WITH_SPACES = re.compile(f"[ \t]*(?:{_TONE_PATTERN}|{_TAG_PATTERN})", re.IGNORECASE)
_SPACES_BEFORE_PUNCTUATION = re.compile(r"[ \t]+([.,!?;:])")
_DOUBLE_SPACES = re.compile(r"[ \t]{2,}")


def tone_of(text: str) -> str | None:
    """The tone a reply asks for: its first tone marker, else None. "<tone:wry>You paid twice?" -> "wry";
    "<TONE:Calm>Breathe." -> "calm"; "Plain answer." -> None; "<tone:grumpy>Hi" -> None (not a Libra tone)."""
    found = TONE_MARKER.search(text)
    if found is None:
        return None
    return found.group(1).lower()


def tidy(text: str) -> str:
    """The text after markers came out: no space left before punctuation, no double spaces, no blank ends.
    "Oh  , really" -> "Oh, really"; "  Hi " -> "Hi"."""
    text = _SPACES_BEFORE_PUNCTUATION.sub(r"\1", text)
    text = _DOUBLE_SPACES.sub(" ", text)
    return text.strip()


def hidden(text: str) -> str:
    """The reply as people see it: every tone marker and sound tag taken out. "<tone:wry>You paid twice? <laugh> No
    harm." -> "You paid twice? No harm."; "a <b>bold</b> move" -> unchanged (not Libra markup)."""
    if not ANY_MARKER.search(text):
        return text
    return tidy(ANY_MARKER.sub("", text))


_WHOLE_MARKERS = [f"<tone:{tone}>" for tone in TONES] + [f"<{tag}>" for tag in TAGS]


def could_be_marker(start: str) -> bool:
    """Whether text that ends a streamed piece may be the first part of a marker still on its way, so it is held back
    until the next piece shows. "<to" -> True; "<tone:w" -> True; "<lau" -> True; "<div" -> False; "< 5" -> False."""
    lowered = start.lower()
    return any(marker.startswith(lowered) for marker in _WHOLE_MARKERS)


class StreamHider:
    """Hides the markup in a reply that arrives in pieces (the terminal's streamed words). A piece that ends in what
    could be the start of a marker keeps that part back until the next piece completes or rules it out, and spaces at
    a piece's end wait too, so a marker that follows takes them away with it (no double space where it was).
    feed("<to") -> ""; feed("ne:wry>Hi <la") -> "Hi"; feed("ugh> ok") -> " ok"; flush() -> ""."""

    def __init__(self) -> None:
        self.held = ""

    def feed(self, piece: str) -> str:
        text = self.held + piece
        self.held = ""
        cut = text.rfind("<")
        if cut != -1 and ">" not in text[cut:] and could_be_marker(text[cut:]):
            self.held = text[cut:]
            text = text[:cut]
        shown = _MARKER_WITH_SPACES.sub("", text)
        kept = shown.rstrip(" \t")
        self.held = shown[len(kept):] + self.held
        return kept

    def flush(self) -> str:
        rest = _MARKER_WITH_SPACES.sub("", self.held)
        self.held = ""
        return rest


def for_libra(text: str) -> str:
    """The reply as Libra hears it: the tone marker goes (it travels as the style), the sound tags stay, written the way
    Libra knows them. "<tone:wry>You paid twice? <Laugh> No harm." -> "You paid twice? <laugh> No harm."."""
    without_tone = TONE_MARKER.sub("", text)
    lowered = TAG_MARKER.sub(lambda found: found.group(0).lower(), without_tone)
    return tidy(lowered)


def keeping_markers(clean, text: str) -> str:
    """`clean(text)` with the markers kept whole: the read-aloud cleaners drop symbols such as ">" and "_" that the
    markers are made of. Each marker is swapped for a placeholder of plain letters first, then put back.
    keeping_markers(lambda t: t.replace(">", ""), "Hi <laugh> there") -> "Hi <laugh> there"."""
    kept: list[str] = []

    def park(found: re.Match) -> str:
        kept.append(found.group(0))
        return f" QQLIBRA{len(kept) - 1}QQ "

    parked = ANY_MARKER.sub(park, text)
    cleaned = clean(parked)
    for number, marker in enumerate(kept):
        cleaned = cleaned.replace(f"QQLIBRA{number}QQ", marker)
    return tidy(cleaned)


# ── Settings: where the server is, and the tone used when a reply names none ──

def url_problem(url: str) -> str | None:
    """Whether a typed server address can be used: None when it can, else what's wrong.
    "http://127.0.0.1:8794" -> None; "http://studio.local:8794/" -> None; "studio.local:8794" -> "Start the address
    with http:// …"; "" -> "Type the Libra server's address first."."""
    typed = url.strip()
    if not typed:
        return "Type the Libra server's address first."
    if not re.match(r"^https?://[A-Za-z0-9.\-\[\]:]+(:\d+)?/?$", typed):
        return "Start the address with http:// and give only the host and port, for example http://127.0.0.1:8794"
    return None


def server_url(settings: dict) -> str:
    """The Libra server's address from the voice settings, without a trailing slash or /v1.
    {} -> "http://127.0.0.1:8794"; {"libra_url": "http://studio.local:8794/v1/"} -> "http://studio.local:8794"."""
    chosen = str(settings.get("libra_url") or "").strip()
    if not chosen:
        return DEFAULT_URL
    chosen = chosen.rstrip("/")
    return chosen.removesuffix("/v1")


def settings_tone(settings: dict) -> str | None:
    """The tone chosen in Settings, used when a reply names none: {"libra_style": "calm"} -> "calm"; {} -> None;
    {"libra_style": "grumpy"} -> None (not a Libra tone)."""
    chosen = str(settings.get("libra_style") or "").strip().lower()
    if chosen in TONES:
        return chosen
    return None


def tone_to_use(asked: str | None, text: str, settings: dict) -> str | None:
    """The style Libra speaks a piece of text in: the tone the caller passed (the Mac sends the reply's tone with each
    sentence), else the text's own marker, else the Settings tone, else none.
    asked "wry" -> "wry"; nothing asked, "<tone:sad>…" -> "sad"; nothing asked, no marker, Settings "calm" -> "calm";
    asked "grumpy" (not a tone), no marker, no Settings tone -> None."""
    if asked and asked.strip().lower() in TONES:
        return asked.strip().lower()
    marked = tone_of(text)
    if marked is not None:
        return marked
    return settings_tone(settings)


# ── How quickly it talks ──
# Libra reads like a storyteller: unhurried. Odie is talked to, so its speech is played a little quicker, with the
# pitch kept (ffmpeg's atempo). Libra's own "fast" pace changes the reading too, and has no "a little".
SPEEDS = {"normal": 1.0, "brisk": 1.1, "quick": 1.2}
DEFAULT_SPEED = "brisk"


def settings_speed(settings: dict) -> str:
    """The speed chosen in Settings → Voice → Libra: {"libra_speed": "quick"} -> "quick"; {} -> "brisk" (the
    default, a tenth quicker); {"libra_speed": "zoom"} -> "brisk"."""
    chosen = str(settings.get("libra_speed") or "").strip().lower()
    if chosen in SPEEDS:
        return chosen
    return DEFAULT_SPEED


async def quicken(wav: bytes, speed: str) -> bytes:
    """`wav` played `speed` quicker with its pitch kept, through ffmpeg. "normal" (or no ffmpeg, or ffmpeg failing)
    gives the WAV back as it was: a voice at its own speed beats no voice. "brisk" -> about 10% shorter."""
    factor = SPEEDS.get(speed, 1.0)
    if factor == 1.0:
        return wav
    # written to a file, not a pipe: a piped WAV has no lengths in its header, and the Mac app's reader refuses that
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "quicker.wav"
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-filter:a", f"atempo={factor}", str(out),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except FileNotFoundError:
            return wav
        await process.communicate(wav)
        if process.returncode != 0 or not out.exists():
            return wav
        return out.read_bytes()


def has_words(spoken: str) -> bool:
    """Whether a piece of text has anything to say: a letter or digit, or a sound tag. A lone "—" or "…" (a sentence
    split leaves those) is nothing, and isn't sent to Libra. "Okay." -> True; "<laugh>" -> True; "—" -> False."""
    return re.search(r"\w", spoken) is not None

async def available(url: str, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Whether a Libra server answers at `url` (its /health, one quick GET)."""
    try:
        async with httpx.AsyncClient(timeout=2, transport=transport) as client:
            reply = await client.get(f"{url}/health")
    except httpx.HTTPError:
        return False
    return reply.status_code == 200


async def speak(text: str, voice: str, tone: str | None, url: str,
                transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """`text` (sound tags allowed) spoken by Libra as a 24 kHz WAV, with its silent ends trimmed so sentences join
    without gaps. A refused request (a 400) raises ValueError with the server's own words."""
    body = {"input": text, "voice": voice, "response_format": "wav", "trim": True}
    if tone is not None:
        body["style"] = tone
    async with httpx.AsyncClient(timeout=300, transport=transport) as client:
        reply = await client.post(f"{url}/v1/audio/speech", json=body)
    if reply.status_code == 400:
        raise ValueError(refusal(reply))
    reply.raise_for_status()
    return reply.content


def refusal(reply: httpx.Response) -> str:
    """The message in a Libra 400 (OpenAI's error shape), else the plain body."""
    try:
        return str(reply.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return reply.text[:200]
