"""Speech the user can play right in the chat: a voice memo, or a two-host podcast (odie.media)."""
from __future__ import annotations

import re
from collections import Counter

import httpx
from google.adk.tools import FunctionTool

from odie import media, voice
from odie.signin import guard

MAX_TURNS = 60
# "Name:" at the start of a line: one to three words in any script, starting with a letter, with no digits ("At 10:30"
# and "Step 1:" aren't names).
_HOST = re.compile(r"^\s*\**\s*([^\W\d_][^\s:\d*]{0,20}(?: [^\W\d_][^\s:\d*]{0,20}){0,2})\s*\**\s*:\s*\**\s*(.*)$")
_TWO = "A podcast has two hosts, a woman and then a man"


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


def parse_script(script: str) -> list[tuple[str, str]]:
    """A podcast script, one turn per line ("Name: what they say"), as [(host, plain speech)]. The first two names are
    the hosts. A line without one of them continues the turn before, even with a colon in it ("At 10:30 we…",
    "Note: …"), unless it names a third speaker more than once. ValueError, in plain words, unless there are exactly two
    hosts with something to say and at most 60 turns."""
    lines = [raw for raw in (script or "").splitlines() if raw.strip()]
    found = [(m.group(1).strip(), m.group(2), raw) if (m := _HOST.match(raw)) else (None, raw, raw) for raw in lines]
    seen = Counter(n for n, _, _ in found if n)
    hosts: list[str] = []
    turns: list[list[str]] = []
    for name, text, raw in found:
        if name and name not in hosts and len(hosts) < 2:
            hosts.append(name)
        if name in hosts:
            turns.append([name, text])
        elif name and seen[name] > 1:
            raise ValueError(f"{_TWO}; this script also has {name}.")
        elif turns:
            turns[-1][1] += " " + raw
        else:
            raise ValueError('Write each line as Host A: or Host B: and what they say (for example, "Host A: Today we\'re looking at…").')
    if len(hosts) != 2:
        raise ValueError(f"{_TWO}; this script has {len(hosts)}.")
    if len(turns) > MAX_TURNS:
        raise ValueError(f"A podcast has at most {MAX_TURNS} turns; this script has {len(turns)}.")
    spoken = [(n, t) for n, t in ((n, plain_speech(t)) for n, t in turns) if t]
    if len({n for n, _ in spoken}) != 2:
        raise ValueError(f"{_TWO}, and each needs something to say (a link or code alone isn't spoken).")
    return spoken


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
    async def speak(script: str, title: str = "", style: str = "memo", voice_name: str = "") -> dict:
        """Read text aloud into audio the user can play right in the chat: the player appears under your reply.

        style="memo": a voice memo, when the user asks for a voice memo, a voice note, or to hear something. `script`
        is what to say, as plain speech, at most about 4,000 characters (some 4 minutes; split longer narration into
        several memos); it's read in the voice chosen in Settings. `voice_name` (optional) is another
        voice for this one memo, only when the user asks for one ("a man's voice"): a voice of the same engine as the
        Settings voice, by name ("Michael"); another engine's voice is refused with the list to pick from.
        style="podcast": a podcast with two hosts. Load the podcast skill first and follow it; `script` is one turn
        per line, "Host A: what they say". The first host to speak gets a woman's voice, the second a man's.
        `title` is short (optional). The result's `path` is the saved WAV file (kept), for a skill to use, e.g. with
        ffmpeg. When it works, reply in one short line; don't repeat the script."""
        kind = (style or "memo").strip().lower()
        if kind not in ("memo", "podcast"):
            return {"error": "style is memo or podcast."}
        try:
            if kind == "memo":
                text = plain_speech(script)
                if not text:
                    return {"error": "There's nothing to say: pass the words to speak as script."}
                eng, vid = voice.get_tts(store)
                if voice_name.strip():
                    vid = voice.voice_in_chosen_engine(store, voice_name)["id"]
                audio = await voice.speak_wav(store, text, voice=vid, transport=transport)
                info = media.wav_info(audio)
                m = media.save(audio, "memo", "wav", "audio/wav", title or _title(text), {**info, "transcript": text, "voice": _label(eng, vid)})
                return {"result": f"The voice memo ({info['duration']:g} s) is under your reply, ready to play.", "media": _short(m),
                        "path": _path(m)}
            turns = parse_script(script)
            woman, man = voice.podcast_voices(store)
            hosts = list(dict.fromkeys(n for n, _ in turns))
            by = {hosts[0]: woman, hosts[1]: man}
            parts = [await voice.speak_wav(store, text, voice=by[n]["id"], transport=transport) for n, text in turns]
            audio, starts = media.join_wavs(parts)
            info = media.wav_info(audio)
            meta = {**info, "hosts": [{"name": h, "voice": by[h]["label"], "group": by[h]["group"]} for h in hosts],
                    "transcript": [{"host": n, "text": t, "start": s} for (n, t), s in zip(turns, starts)]}
            m = media.save(audio, "podcast", "wav", "audio/wav", title or _title(turns[0][1]), meta)  # no title: the opening line, never the hosts' labels
            mins = max(1, round(info["duration"] / 60))
            return {"result": f"The podcast (about {mins} min, {len(turns)} turns) is under your reply, ready to play.", "media": _short(m),
                    "path": _path(m)}
        except ValueError as e:
            return {"error": str(e)}
        except voice.VoiceUnavailable as e:
            return {"error": str(e)}
        except httpx.HTTPError:
            return {"error": "The voice didn't answer (Settings → Voice). Try again in a moment."}

    return [FunctionTool(speak, require_confirmation=guard.for_speech(store))]  # a cloud voice in a private turn asks first
