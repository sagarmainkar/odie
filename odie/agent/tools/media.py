"""Speech the user can play right in the chat: a voice memo (odie.media). A podcast is made in the background by the
podcast skill's make_podcast (odie.making.podcast), not here."""
from __future__ import annotations

import re

import httpx
from google.adk.tools import FunctionTool

from odie import media, voice
from odie.signin import guard

NOTHING_TO_SAY = "There's nothing to say: pass the words to speak as script."
NO_ANSWER = "The voice didn't answer (Settings → Voice). Try again in a moment."
TWO_HOSTS = ("This script has two hosts, and speak reads everything in one voice, labels included. A podcast with two "
             "hosts is make_podcast (the podcast skill): give it the topic, and this script as its brief.")


def plain_speech(text: str, limit: int = 4000) -> str:
    """Markdown, links and code taken out, each line a sentence: what a voice should read."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)", "", line)
        line = re.sub(r"\*\*|__|`|~~", "", line)
        line = re.sub(r"(?<!\w)[*_](\S[^*_]*?)[*_](?!\w)", r"\1", line)
        line = " ".join(line.split())
        if line:
            lines.append(line if line[-1] in ".!?…:;,।" else line + ".")
    out = " ".join(lines)
    if len(out) > limit:
        cut = out[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        out = cut[: end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0]
    return out


def has_two_hosts(script: str) -> bool:
    """Decides whether a script is a podcast for two hosts rather than a memo: it reads as a podcast script
    (odie.making.podcast_writer.parse_script: two names, each starting their own lines) and every "Name:" line
    belongs to one of those two. "Host A: hi\nHost B: hello" -> True (refused: a podcast); "Remember to buy milk" ->
    False (spoken); "Note: buy milk" -> False (one label isn't two hosts); "Monday: gym\nTuesday: swim\nWednesday:
    rest" -> False (a list of three labels, not two hosts)."""
    # Imported here: the podcast writer imports plain_speech from this module.
    from odie.making.podcast_writer import labelled_line, parse_script

    try:
        turns = parse_script(script)
    except ValueError:
        return False
    hosts = {name for name, _speech in turns}
    for line in script.splitlines():
        name, _text = labelled_line(line)
        if name is not None and name not in hosts:
            return False
    return True


def _title(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= 60 else first[:60].rsplit(" ", 1)[0] + "…"


def _short(m: dict) -> dict:
    """What the model sees of what it made: the chat reads the rest (waveform, transcript) from the sidecar."""
    return {k: m[k] for k in ("id", "kind", "title", "duration")}


def _label(eng: str, vid: str) -> str:
    return next((x["label"] for x in voice.engine_voices(eng) if x["id"] == vid), vid)


def _path(m: dict) -> str:
    """Where the saved audio is, for a skill to hand on (ffmpeg): <data>/media/<id>.wav. Media files are kept."""
    return str(media.media_dir() / f"{m['id']}.{m['ext']}")


def make_media_tools(store, transport: httpx.AsyncBaseTransport | None = None) -> list[FunctionTool]:
    async def speak(script: str, title: str = "", voice_name: str = "") -> dict:
        """Read text aloud as a voice memo the user can play right in the chat: the player appears under your reply.
        Use it when the user asks for a voice memo, a voice note, or to hear something. `script` is what to say, as
        plain speech, at most about 4,000 characters (some 4 minutes; split longer narration into several memos);
        it's read in the voice chosen in Settings. `voice_name` (optional) is another voice for this one memo, only
        when the user asks for one ("a man's voice"): a voice of the same engine as the Settings voice, by name
        ("Michael"); another engine's voice is refused with the list to pick from. `title` is short (optional).
        The result's `path` is the saved WAV file (kept), for a skill to use, e.g. with ffmpeg. When it works, reply
        in one short line; don't repeat the script. A podcast with two hosts is make_podcast (the podcast skill),
        not this."""
        text = plain_speech(script)
        if not text:
            return {"error": NOTHING_TO_SAY}
        if has_two_hosts(script):
            return {"error": TWO_HOSTS}
        try:
            engine, voice_id = voice.get_tts(store)
            if voice_name.strip():
                voice_id = voice.voice_in_chosen_engine(store, voice_name)["id"]
            audio = await voice.speak_wav(store, text, voice=voice_id, transport=transport)
        except ValueError as e:
            return {"error": str(e)}
        except voice.VoiceUnavailable as e:
            return {"error": str(e)}
        except httpx.HTTPError:
            return {"error": NO_ANSWER}

        info = media.wav_info(audio)
        if not title:
            title = _title(text)
        meta = {**info, "transcript": text, "voice": _label(engine, voice_id)}
        m = media.save(audio, "memo", "wav", "audio/wav", title, meta)
        said = f"The voice memo ({info['duration']:g} s) is under your reply, ready to play."
        return {"result": said, "media": _short(m), "path": _path(m)}

    # A cloud voice in a private turn asks first.
    return [FunctionTool(speak, require_confirmation=guard.for_speech(store))]
