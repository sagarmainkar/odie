"""Voice through OpenAI: read-aloud (gpt-4o-mini-tts), dictation (gpt-4o-mini-transcribe) and realtime talk
(gpt-realtime-2.1-mini over WebRTC). The API key stays on this computer; the phone only ever gets a short-lived
realtime client secret.

Realtime design: the voice model handles the conversation itself, but anything about the user's world (mail,
calendar, money, notes, reminders, memory, web, actions) goes through ONE tool, ask_brain, which runs a normal
Odie turn (Gemma, all tools, approvals, memory). So OpenAI sees the spoken conversation, not raw mail or ledger
data, and every real action still gets an approval card."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import struct

import httpx

from odie import config, machine
from odie.secrets import load_secret
from odie.store.db import Store

log = logging.getLogger("odie.voice")

API = "https://api.openai.com/v1"
TTS_MODEL = "gpt-4o-mini-tts"  # the default; the tts_model setting (ODIE_TTS_MODEL) names another
STT_MODEL = "gpt-4o-mini-transcribe"  # the default; stt_model (ODIE_STT_MODEL). Deprecated 26 Feb 2027: gpt-transcribe
REALTIME_MODEL = "gpt-realtime-2.1-mini"
DEFAULT_VOICE = "marin"
# Voices that work for BOTH read-aloud and realtime (checked against the API on 2026-10-01), so one choice covers both.
# Grouped by how they usually sound (OpenAI doesn't label voices by gender; this is a listening guide, not a fact).
_GROUPS = {"female": ["marin", "coral", "sage", "shimmer"], "male": ["cedar", "ash", "ballad", "echo", "verse"], "neutral": ["alloy"]}
VOICES = [{"id": v, "label": v.capitalize(), "group": g} for g, ids in _GROUPS.items() for v in ids]
_VOICE_IDS = {v["id"] for v in VOICES}


def tts_model() -> str:
    """The OpenAI read-aloud model: the tts_model setting, else TTS_MODEL, so a retired model is a settings change.
    No setting -> "gpt-4o-mini-tts"; ODIE_TTS_MODEL=gpt-next-tts -> "gpt-next-tts"."""
    chosen = config.settings.tts_model.strip()
    return chosen or TTS_MODEL


def stt_model() -> str:
    """The OpenAI model dictation and live talk transcribe with: the stt_model setting, else STT_MODEL.
    No setting -> "gpt-4o-mini-transcribe"; ODIE_STT_MODEL=gpt-transcribe -> "gpt-transcribe"."""
    chosen = config.settings.stt_model.strip()
    return chosen or STT_MODEL


def tts_style(country: str) -> str:
    """How OpenAI voice should sound; amounts read the local way."""
    base = "Warm, calm and unhurried, like a thoughtful friend."
    return base + (" Indian English context: say rupee amounts naturally." if country == "IN" else " Say amounts naturally.")


def transcription_prompt(country: str) -> str:
    """A hint for speech-to-text about the accent; empty when there's nothing useful to say."""
    return "Indian English." if country == "IN" else ""


# ── Read-aloud engines: OpenAI (cloud), Kokoro and Maya1 (Odie's own voice worker, odie.voice_worker) ──
def local_url() -> str:
    """Odie's own voice worker (odie.voice_worker), on its own port: never another app's voice service."""
    from odie.voice_worker import voice_port
    return f"http://127.0.0.1:{voice_port()}"
KOKORO_VOICES = [
    {"id": "af_heart", "label": "Heart", "group": "female", "lang": "a", "note": "American"},
    {"id": "af_bella", "label": "Bella", "group": "female", "lang": "a", "note": "American"},
    {"id": "bf_emma", "label": "Emma", "group": "female", "lang": "b", "note": "British"},
    {"id": "hf_alpha", "label": "Alpha", "group": "female", "lang": "h", "note": "Indian"},
    {"id": "hf_beta", "label": "Beta", "group": "female", "lang": "h", "note": "Indian"},
    {"id": "am_michael", "label": "Michael", "group": "male", "lang": "a", "note": "American"},
    {"id": "am_fenrir", "label": "Fenrir", "group": "male", "lang": "a", "note": "American"},
    {"id": "bm_george", "label": "George", "group": "male", "lang": "b", "note": "British"},
    {"id": "hm_omega", "label": "Omega", "group": "male", "lang": "h", "note": "Indian"},
    {"id": "hm_psi", "label": "Psi", "group": "male", "lang": "h", "note": "Indian"},
]
MAYA_VOICES = [
    {"id": "in_female", "label": "Indian", "group": "female", "note": "30s, warm",
     "description": "Realistic female voice in her 30s with an indian accent. Normal pitch, warm timbre, conversational pacing."},
    {"id": "uk_female", "label": "British", "group": "female", "note": "30s, smooth",
     "description": "Realistic female voice in her 30s with a british accent. Normal pitch, smooth timbre, conversational pacing."},
    {"id": "in_male", "label": "Indian", "group": "male", "note": "30s, deep",
     "description": "Realistic male voice in his 30s with an indian accent. Low pitch, deep timbre, conversational pacing."},
    {"id": "us_male", "label": "American", "group": "male", "note": "40s, warm",
     "description": "Realistic male voice in his 40s with an american accent. Normal pitch, warm timbre, conversational pacing."},
]
MAYA_TAGS = ["laugh", "laugh_harder", "sigh", "chuckle", "gasp", "angry", "excited", "whisper", "cry", "scream", "sing",
             "snort", "exhale", "gulp", "giggle", "sarcastic", "curious"]
ENGINES = {
    "openai": {"label": "OpenAI", "note": "gpt-4o-mini-tts. Natural, quick, text goes to OpenAI.", "local": False},
    "kokoro": {"label": "Kokoro", "note": "On this computer. Instant, no expressions.", "local": True},
    "maya1": {"label": "Maya1", "note": "On this computer. Expressive (laughs, sighs), takes about twice the speech length to prepare; long replies are summarised.", "local": True},
    "phonon": {"label": "Phonon (Ollama)", "note": "On this computer through Ollama. Quick, streams, no expressions.", "local": True},
}
# Maya1 is hidden until its pipeline is rebuilt from the official prompt format (2026-10-01: through mlx-audio's generic
# loader it read tags out as words or produced noise).
_HIDDEN = {"maya1"}
OWN_SERVER = {"kokoro", "maya1"}  # the engines Odie's own voice server speaks (odie.voice_worker); Phonon is Ollama's


def disabled() -> set[str]:
    """The engines not offered on this machine: Maya1 always (above), and the ones Odie's own voice server speaks when
    that server isn't meant to run here (ODIE_VOICE=off: an Intel Mac, see odie.machine). Phonon runs in Ollama, so it
    is offered everywhere. An M2 -> {"maya1"}; an Intel Mac -> {"maya1", "kokoro"}."""
    if machine.local_voice_wanted():
        return set(_HIDDEN)
    return _HIDDEN | OWN_SERVER


def default_engine() -> str:
    """The engine when none is chosen, or the chosen one isn't offered here: Phonon when Ollama had it the last time
    Odie asked (phonon_here), else Kokoro where Odie's own voice runs, else OpenAI (which needs its key; without one,
    read-aloud says so). Ollama with phonon, on any Mac -> "phonon"; no phonon, an M2 -> "kokoro"; no phonon, an Intel
    Mac -> "openai"."""
    if phonon_here():
        return "phonon"
    if machine.local_voice_wanted():
        return "kokoro"
    return "openai"


def _chosen_engine(s: dict) -> str:
    """The engine the settings name, when it is offered here; else the default. {"engine": "kokoro"} on an M2 ->
    "kokoro"; the same on an Intel Mac -> "openai"; {} -> the default."""
    engine = s.get("engine")
    if engine in ENGINES and engine not in disabled():
        return engine
    return default_engine()
_ENGINE_VOICES = {"openai": VOICES, "kokoro": KOKORO_VOICES, "maya1": MAYA_VOICES}
_DEFAULT_VOICE = {"openai": DEFAULT_VOICE, "kokoro": "af_heart", "maya1": "in_female"}


def engine_voices(engine: str) -> list[dict]:
    """An engine's voices. Phonon's are the ones Ollama listed (phonon_voices), kept for the process; before Ollama has
    been asked, the one voice that always works, "default"."""
    if engine == "phonon":
        return list(_PHONON_VOICES.get(PHONON_MODEL) or [PHONON_DEFAULT])
    return _ENGINE_VOICES.get(engine, [])


def default_voice(engine: str) -> str:
    """The voice an engine speaks in when none of its voices is chosen: Phonon's from what Ollama lists
    (default_phonon_voice), the others' fixed ones. "kokoro" -> "af_heart"; "phonon" with Zoey listed -> "zoey"."""
    if engine == "phonon":
        return default_phonon_voice(engine_voices("phonon"))
    return _DEFAULT_VOICE[engine]


def voice_is_offered(engine: str, voice_id: str | None) -> bool:
    """Whether a saved or asked-for voice can be used with this engine. Kokoro's and OpenAI's are a fixed list. Phonon's
    are whatever Ollama listed; before Odie has asked Ollama (a restart), a saved Phonon voice is trusted, since Ollama
    is the one to say no (it answers 400, said plainly by phonon_tts). "af_heart" for kokoro -> True; "nova" for
    openai -> False; "easton" for phonon with Ollama's list read and Easton on it -> True; "easton" for phonon before
    the list is read -> True; "nobody" for phonon with the list read -> False."""
    if not voice_id:
        return False
    if engine == "phonon" and PHONON_MODEL not in _PHONON_VOICES:
        return True
    return voice_id in {x["id"] for x in engine_voices(engine)}


def _local_instead_of_openai() -> str | None:
    """The engine read-aloud uses when OpenAI is chosen but its key is gone: Phonon when Ollama has it, else Kokoro
    where it runs, else none (read-aloud then says the key is missing). Ollama with phonon -> "phonon"; an M2 without
    it -> "kokoro"; an Intel Mac without it -> None."""
    if phonon_here():
        return "phonon"
    if "kokoro" not in disabled():
        return "kokoro"
    return None


def get_tts(store: Store) -> tuple[str, str]:
    """(engine, voice) for read-aloud. The realtime Talk voice is get_voice() (OpenAI only)."""
    s = store.get_setting("voice") or {}
    engine = _chosen_engine(s)
    if engine == "openai" and not load_secret("OPENAI_API_KEY"):
        engine = _local_instead_of_openai() or engine  # OpenAI voices need its key
    v = s.get("voice") if engine == "openai" else s.get(f"{engine}_voice")
    return engine, (v if voice_is_offered(engine, v) else default_voice(engine))


def video_tts(store: Store) -> tuple[str, str]:
    """(engine, voice) videos are narrated in. The video_voice setting (ODIE_VIDEO_VOICE) pins the channel's voice apart
    from read-aloud, so changing the read-aloud voice leaves videos alone; unset, videos speak in the read-aloud voice,
    as before. The pinned voice is found by its id or name in any engine offered here, and stays even when it is
    OpenAI's and the key is gone (the video then says the key is missing rather than change voice).
    ODIE_VIDEO_VOICE=cedar, read-aloud Kokoro Heart -> ("openai", "cedar"); unset -> ("kokoro", "af_heart");
    "nobody", or a Kokoro voice on an Intel Mac (no Kokoro there) -> the read-aloud voice, and the log says why."""
    pinned = config.settings.video_voice.strip().lower()
    if not pinned:
        return get_tts(store)
    for engine in ENGINES:
        if engine in disabled():
            continue
        for v in engine_voices(engine):
            if pinned in (v["id"], v["label"].lower()):
                return engine, v["id"]
    log.warning("video_voice %r isn't a voice offered here; videos speak in the read-aloud voice", pinned)
    return get_tts(store)


def set_tts(store: Store, engine: str | None = None, voice: str | None = None) -> tuple[str, str]:
    s = dict(store.get_setting("voice") or {})
    if engine in ENGINES and engine not in disabled():
        s["engine"] = engine
    eng = _chosen_engine(s)  # the same default as get_tts
    if voice and voice_is_offered(eng, voice):
        s["voice" if eng == "openai" else f"{eng}_voice"] = voice
    store.set_setting("voice", s)
    return get_tts(store)


def worker_wanted(store: Store) -> bool:
    """Whether read-aloud uses Odie's own voice server (odie.voice_worker), so it should run: the engine read-aloud
    speaks with is one that server speaks (OWN_SERVER). Kokoro chosen -> True; Phonon chosen -> False; OpenAI with its
    key -> False."""
    engine, _ = get_tts(store)
    return engine in OWN_SERVER


async def settle_worker(store: Store) -> None:
    """After the read-aloud engine changes: Odie's own voice server is stopped when read-aloud no longer uses it, so the
    process goes away. When it does use it, nothing happens now: the next speech starts it (local_tts asks the worker
    to be up first). Called by the async callers of set_tts, which is synchronous."""
    from odie import voice_worker
    worker = voice_worker.current
    if worker is None or worker_wanted(store):
        return
    await worker.stop()


SCRIPT_PROMPT = ("Rewrite the assistant's reply below as a short script for a voice actor to read aloud to the user. Plain speech: "
                 "no markdown, no lists, no URLs or ids; numbers and amounts the way people say them. Keep the meaning, at most "
                 "80 words; if the reply is longer, speak a natural summary of it. Where it genuinely fits the mood, add one to three "
                 "expression tags, chosen only from: {tags}. Tags look like <laugh> and go inline, e.g. 'Good news! <excited> The market is "
                 "up.' Never more than three, none if the reply is plain information. Output only the script.")


async def maya_script(text: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """Local Gemma (LM Studio) turns a reply into a speech script with a few Maya1 expression tags. Stays on this computer."""
    from odie import config
    from odie.sampling import VOICE_SCRIPT_TEMPERATURE
    base = config.settings.lm_studio_base_url
    async with httpx.AsyncClient(timeout=90, transport=transport) as c:
        model = config.settings.model_id
        try:  # use whatever chat model LM Studio already has loaded, so this never triggers a model load
            r = await c.get(base.replace("/v1", "/api/v0") + "/models")
            loaded = [m["id"] for m in r.json().get("data", []) if m.get("state") == "loaded" and m.get("type") in ("llm", "vlm")]
            if loaded:
                model = loaded[0]
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        r = await c.post(base + "/chat/completions", json={
            "model": model, "temperature": VOICE_SCRIPT_TEMPERATURE, "max_tokens": 220, "reasoning_effort": "none",
            "messages": [{"role": "system", "content": SCRIPT_PROMPT.format(tags=", ".join(f"<{x}>" for x in MAYA_TAGS))},
                         {"role": "user", "content": text[:4000]}]})
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip()


async def local_tts(engine: str, text: str, voice: str, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """`text` spoken on this computer as WAV bytes: Phonon through Ollama, or Kokoro and Maya1 through Odie's own voice
    server (started again if it died)."""
    if engine == "phonon":
        return await phonon_tts(text, voice, transport=transport)
    if engine == "kokoro":
        v = next((x for x in KOKORO_VOICES if x["id"] == voice), KOKORO_VOICES[0])
        body = {"engine": "kokoro", "text": text, "voice": v["id"], "lang": v["lang"]}
    else:
        v = next((x for x in MAYA_VOICES if x["id"] == voice), MAYA_VOICES[0])
        body = {"engine": "maya1", "text": f'<description="{v["description"]}"> {text}'}
    from odie import voice_worker
    w = voice_worker.current
    if w is not None and transport is None and not await w.ensure():  # started again if it died
        raise VoiceUnavailable(w.problem or "Odie's local voice isn't running.")
    async with httpx.AsyncClient(timeout=300, transport=transport) as c:
        r = await c.post(f"{local_url()}/tts", json=body)
        r.raise_for_status()
        return r.content


async def local_available(transport: httpx.AsyncBaseTransport | None = None) -> bool:
    from odie import voice_worker
    if voice_worker.current is not None and transport is None:
        return await voice_worker.current.healthy()  # Odie's own worker, not whatever answers on the port
    try:
        async with httpx.AsyncClient(timeout=2, transport=transport) as c:
            return (await c.get(f"{local_url()}/health")).status_code == 200
    except httpx.HTTPError:
        return False


async def own_server_can_speak() -> bool:
    """Whether Kokoro can be chosen now: Odie's own voice server answers, or it is set up and would start the first time
    Kokoro speaks (it runs only while read-aloud uses it, so with Phonon chosen it is stopped). Running -> True; set up
    but stopped -> True; never set up (no `uv sync` in voice_server) -> False."""
    from odie import voice_worker
    worker = voice_worker.current
    if worker is None:
        return await local_available()
    if await worker.healthy():
        return True
    return bool(worker.installed)


async def speak(store: Store, text: str, engine: str | None = None, voice: str | None = None) -> tuple[bytes, str]:
    """Read-aloud with the chosen engine. Returns (audio, media type). Maya1 gets a tagged script from local Gemma first."""
    eng, v = get_tts(store)
    eng, v = engine or eng, voice or v
    if eng == "openai":
        return await tts(text, v), "audio/mpeg"
    if eng == "maya1":
        try:
            text = await maya_script(text) or text
        except (httpx.HTTPError, KeyError, ValueError):
            pass
    return await local_tts(eng, text, v), "audio/wav"


async def speak_wav(store: Store, text: str, voice: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                    engine: str | None = None, style: str = "") -> bytes:
    """`text` as a 16-bit WAV in the chosen engine (a voice memo, a podcast's turn). OpenAI is asked for raw PCM, so
    both engines' audio joins alike. `engine` with `voice` speaks in that engine instead (a video's own voice,
    video_tts). `style` steers an OpenAI voice for this text (tts); Kokoro and Phonon have no steering and never see it."""
    from odie.media import pcm_to_wav
    eng, v = get_tts(store)
    if engine and voice:
        eng, v = engine, voice
    if eng == "openai":
        return pcm_to_wav(await tts(text, voice or v, transport=transport, fmt="pcm", style=style))
    if eng == "phonon":
        return await phonon_tts(text, voice or v, transport=transport)
    return await local_tts("kokoro", text, voice or (v if eng == "kokoro" else _DEFAULT_VOICE["kokoro"]), transport=transport)


def reminders_spoken(store: Store) -> bool:
    """Settings → Voice → Speak reminders: each reminder also arrives as a voice memo in the chosen voice."""
    return bool((store.get_setting("voice") or {}).get("reminders_spoken"))


def set_reminders_spoken(store: Store, on: bool) -> None:
    s = dict(store.get_setting("voice") or {})
    s["reminders_spoken"] = bool(on)
    store.set_setting("voice", s)


TALK_HELD_BACK = True  # Talk (a live voice conversation through OpenAI) is kept out of the app for now (13 Oct 2026)


def dictation_available() -> bool:
    """Live dictation (words appear as you speak, through OpenAI) is there whenever the OpenAI key is: the key already
    says the owner is fine with OpenAI's voices. Example: key present -> True; no key -> False (the phone's own
    dictation is used instead)."""
    return bool(load_secret("OPENAI_API_KEY"))


# ── Phonon through Ollama: the voices it lists, its speech route, long text split and joined ──
PHONON_MODEL = "phonon"
PHONON_MAX_CHARS = 4000  # Ollama takes up to 4,096 characters a request; a little room under that
PHONON_DEFAULT = {"id": "default", "label": "Default", "group": ""}  # the voice Phonon always has
PULL_PHONON = "Ollama doesn't have phonon: run `ollama pull phonon` (113 MB), then choose it again."
_PHONON_VOICES: dict[str, list[dict]] = {}  # model -> the voices Ollama listed for it, read once per process
_PHONON_SEEN: dict[str, bool] = {}  # "here" -> whether Ollama had a phonon model the last time Odie asked
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def ollama_root() -> str:
    """Ollama's own address (no /v1), from the OLLAMA_BASE_URL setting the chat side reads (odie.models): nothing set ->
    "http://localhost:11434"; OLLAMA_BASE_URL=http://studio.local:11434/v1 -> "http://studio.local:11434"."""
    from odie.models import OLLAMA_BASE_URL, provider_base_url
    url = provider_base_url("ollama", OLLAMA_BASE_URL)
    return url.removesuffix("/v1")


def forget_phonon() -> None:
    """Drops what this process learnt about Phonon (its voices, whether Ollama has it): the next ask goes to Ollama."""
    _PHONON_VOICES.clear()
    _PHONON_SEEN.clear()


def phonon_here() -> bool:
    """Whether Ollama had a phonon model the last time Odie asked (phonon_available); False before it has asked."""
    return _PHONON_SEEN.get("here", False)


def voice_label(name: str) -> str:
    """How a voice name Ollama lists is shown: capitalised when Ollama spells it all lower-case, else as Ollama spells
    it. "zoey" -> "Zoey"; "Captain Silas Blackwater" -> as it is; "ZOEY" -> as it is."""
    if name == name.lower():
        return name.capitalize()
    return name


def phonon_voice(name: str) -> dict:
    """One voice Ollama lists, as the picker shows it."""
    return {"id": name, "label": voice_label(name), "group": ""}


def default_phonon_voice(voices: list[dict]) -> str:
    """The Phonon voice used when none is chosen: Zoey when Ollama lists her (in any case), else the first voice it
    lists, else "default", which Phonon always has. [freya, ZOEY] -> "ZOEY"; [freya, easton] -> "freya"; [] ->
    "default"."""
    for v in voices:
        if v["id"].lower() == "zoey":
            return v["id"]
    if voices:
        return voices[0]["id"]
    return PHONON_DEFAULT["id"]


def _names_in(listed) -> list[str]:
    """The voice names in /api/show's `voices`: plain names, or objects with a name. Blank ones are dropped."""
    names = []
    for item in listed or []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


async def phonon_voices(transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Phonon's voices, as Ollama lists them (POST /api/show {"model": "phonon"}), asked once per process and kept, so
    Settings opening again doesn't ask Ollama again. "default" alone when the list is empty or Ollama can't be asked;
    that answer isn't kept, so the next open asks again."""
    kept = _PHONON_VOICES.get(PHONON_MODEL)
    if kept:
        return list(kept)
    try:
        async with httpx.AsyncClient(timeout=5, transport=transport) as c:
            r = await c.post(f"{ollama_root()}/api/show", json={"model": PHONON_MODEL})
        r.raise_for_status()
        names = _names_in(r.json().get("voices"))
    except (httpx.HTTPError, ValueError, AttributeError):
        names = []
    if not names:
        return [dict(PHONON_DEFAULT)]
    listed = [phonon_voice(n) for n in names if n.lower() != "default"] or [dict(PHONON_DEFAULT)]
    _PHONON_VOICES[PHONON_MODEL] = listed
    return list(listed)


async def ollama_models(transport: httpx.AsyncBaseTransport | None = None) -> list[str] | None:
    """The models Ollama has (GET /api/tags), by name; None when Ollama can't be asked, so "no Ollama" and "Ollama
    without phonon" can be told apart. Ollama with phonon and gemma -> ["phonon:latest", "gemma4:e4b"]; Ollama with
    nothing -> []; no Ollama -> None."""
    try:
        async with httpx.AsyncClient(timeout=3, transport=transport) as c:
            r = await c.get(f"{ollama_root()}/api/tags")
        r.raise_for_status()
        models = r.json().get("models") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return [str(m.get("name") or m.get("model") or "") for m in models if isinstance(m, dict)]


async def phonon_models(transport: httpx.AsyncBaseTransport | None = None) -> list[str]:
    """The Phonon models Ollama has: every model whose name starts with "phonon", as Ollama names them
    ("phonon:latest", "phonon:fr"); [] when there are none or Ollama can't be asked."""
    names = await ollama_models(transport) or []
    return [n for n in names if n.startswith("phonon")]


async def phonon_available(transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Whether Phonon can speak here: Ollama answers and has a model whose name starts with "phonon". Remembered for
    default_engine. Ollama with phonon:latest -> True; only phonon:fr -> True; no phonon, or no Ollama -> False."""
    here = bool(await phonon_models(transport))
    _PHONON_SEEN["here"] = here
    return here


def split_for_phonon(text: str, limit: int = PHONON_MAX_CHARS) -> list[str]:
    """`text` in pieces Ollama takes (at most `limit` characters each), cut at sentence ends; a single sentence longer
    than that is cut at its last space before the limit. A 9,000-character reply of short sentences -> three pieces;
    "Short. Two." -> ["Short. Two."]."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text.strip()):
        sentence = sentence.strip()
        while len(sentence) > limit:  # no sentence end in reach: cut at a space
            cut = sentence.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        joined = f"{current} {sentence}" if current else sentence
        if len(joined) <= limit:
            current = joined
            continue
        pieces.append(current)
        current = sentence
    if current:
        pieces.append(current)
    return pieces


def _wav_parts(wav: bytes) -> tuple[bytes, int]:
    """The PCM in one WAV from Ollama and its sample rate. Its size fields can't be trusted (it streams before it knows
    the length), so the PCM is everything after the data chunk's header. No fmt chunk -> Phonon's 24 kHz."""
    rate = 24000
    fmt_at = wav.find(b"fmt ")
    if fmt_at != -1 and len(wav) >= fmt_at + 16:
        rate = struct.unpack("<I", wav[fmt_at + 12:fmt_at + 16])[0]
    data_at = wav.find(b"data")
    if data_at == -1:
        return b"", rate
    return wav[data_at + 8:], rate


def join_wavs(wavs: list[bytes]) -> bytes:
    """Ollama's WAVs (16-bit mono) as one WAV: their PCM end to end, under one header whose sizes are right."""
    from odie.media import pcm_to_wav
    pcm = io.BytesIO()
    rate = 24000
    for i, wav in enumerate(wavs):
        part, part_rate = _wav_parts(wav)
        if i == 0:
            rate = part_rate
        pcm.write(part)
    return pcm_to_wav(pcm.getvalue(), rate=rate)


def phonon_problem(status: int, body: str, voice_id: str) -> str:
    """What to tell the user when Ollama refuses a Phonon request: the model isn't pulled (`ollama pull phonon`), the
    voice isn't one Phonon has, or Ollama's own words. 404 "model \"phonon\" not found" -> PULL_PHONON;
    400 "voice \"Nobody\" not found" -> "Phonon has no voice called \"Nobody\"…"; 500 "out of memory" -> "Ollama
    couldn't speak that (500): out of memory"."""
    said = body
    try:
        error = json.loads(body).get("error")
    except (ValueError, AttributeError):
        error = None
    if isinstance(error, dict):
        said = str(error.get("message") or body)
    elif error:
        said = str(error)
    lowered = said.lower()
    if "voice" in lowered and "not found" in lowered:
        return f'Phonon has no voice called "{voice_id}": choose another in Settings → Voice.'
    if status == 404 or ("model" in lowered and "not found" in lowered):
        return PULL_PHONON
    return f"Ollama couldn't speak that ({status}): {said[:160]}"


async def _phonon_piece(client: httpx.AsyncClient, text: str, voice_id: str, model: str) -> bytes:
    """One request to Ollama's speech route; the WAV bytes, or VoiceUnavailable with a reason a person can act on."""
    body = {"model": model, "input": text, "voice": voice_id, "response_format": "wav"}
    try:
        r = await client.post(f"{ollama_root()}/v1/audio/speech", json=body)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise VoiceUnavailable(f"Ollama isn't answering at {ollama_root()}: start Ollama, then try again.") from e
    if r.status_code != 200:
        raise VoiceUnavailable(phonon_problem(r.status_code, r.text, voice_id))
    return r.content


async def phonon_tts(text: str, voice_id: str, transport: httpx.AsyncBaseTransport | None = None, model: str = PHONON_MODEL) -> bytes:
    """`text` spoken by Phonon through Ollama as one WAV: long text in sentence-sized pieces (split_for_phonon), asked
    one after another, joined (join_wavs). Nothing leaves this computer but the request to Ollama."""
    wavs = []
    async with httpx.AsyncClient(timeout=300, transport=transport) as c:
        for piece in split_for_phonon(text):
            wavs.append(await _phonon_piece(c, piece, voice_id, model))
    return join_wavs(wavs)


_PAIRS = {"a": ("af_heart", "am_michael"), "b": ("bf_emma", "bm_george"), "h": ("hf_alpha", "hm_omega")}


def phonon_hosts(voices: list[dict], chosen: str) -> list[dict]:
    """A podcast's two hosts when Phonon speaks: the chosen voice first, then another of Phonon's: Easton (or Zoey when
    Easton is the chosen one) when Ollama lists them, else the first other voice it lists. One voice only (Phonon's
    "default") -> that voice for both. [zoey, easton, freya] with freya chosen -> [freya, easton]; with easton chosen
    -> [easton, zoey]."""
    by_id = {v["id"]: v for v in voices}
    first = by_id.get(chosen) or (voices[0] if voices else dict(PHONON_DEFAULT))
    partner_name = "zoey" if first["id"].lower() == "easton" else "easton"
    others = [v for v in voices if v["id"] != first["id"]]
    partner = next((v for v in others if v["id"].lower() == partner_name), others[0] if others else first)
    return [first, partner]


def podcast_voices(store: Store) -> list[dict]:
    """A podcast's two hosts, [a woman, a man], from the chosen engine and with the chosen voice's accent; the chosen
    voice is one of them. Phonon's two come from the voices Ollama lists (phonon_hosts)."""
    eng, v = get_tts(store)
    if eng == "phonon":
        return phonon_hosts(engine_voices("phonon"), v)
    if eng != "openai":
        eng, v = "kokoro", v if v in {x["id"] for x in KOKORO_VOICES} else _DEFAULT_VOICE["kokoro"]
    voices = {x["id"]: x for x in engine_voices(eng)}
    chosen = voices[v]
    woman, man = ("marin", "cedar") if eng == "openai" else _PAIRS.get(chosen.get("lang", "a"), _PAIRS["a"])
    if chosen["group"] == "female":
        woman = v
    elif chosen["group"] == "male":
        man = v
    return [voices[woman], voices[man]]


_GROUP_NAMES = {"female": "women", "male": "men", "neutral": "neutral"}
_WHO = {"female": "a woman", "male": "a man", "neutral": "neutral"}


def voice_summary(v: dict) -> str:
    """One voice as the model reads it: "Heart (American, a woman)"; OpenAI's have no accent: "Cedar (a man)"."""
    about = [x for x in (v.get("note"), _WHO.get(v["group"])) if x]
    return f"{v['label']} ({', '.join(about)})"


def voices_text(engine: str) -> str:
    """An engine's voices grouped by who they sound like, with the accent when there is one:
    "kokoro" -> "women: Heart (American), Bella (American), …; men: Michael (American), …"."""
    groups: dict[str, list[str]] = {}
    for v in engine_voices(engine):
        name = f"{v['label']} ({v['note']})" if v.get("note") else v["label"]
        groups.setdefault(v["group"], []).append(name)
    return "; ".join(f"{_GROUP_NAMES.get(g, g or 'voices')}: {', '.join(names)}" for g, names in groups.items())


def voice_in_chosen_engine(store: Store, asked: str) -> dict:
    """The voice the model asked for, by its id or label in any case, only from the engine chosen in Settings: switching
    engines would send the text to the cloud (Kokoro to OpenAI) or undo the user's choice (OpenAI to Kokoro). Settings
    are not changed. ValueError, listing the voices it can use, for anything else.
    Kokoro chosen: "Michael" -> am_michael; " AM_FENRIR " -> am_fenrir; "cedar" (OpenAI's) -> ValueError."""
    engine, _ = get_tts(store)
    wanted = (asked or "").strip().lower()
    for v in engine_voices(engine):
        if wanted in (v["id"], v["label"].lower()):
            return v
    label = ENGINES[engine]["label"]
    raise ValueError(f"'{asked}' isn't one of {label}'s voices, the engine chosen in Settings. {label}'s voices: "
                     f"{voices_text(engine)}. Another engine is the user's choice, in Settings > Voice.")


class VoiceUnavailable(RuntimeError):
    """A voice that can't speak right now: no OpenAI key, or Odie's local voice isn't running (the message says why)."""


def api_key() -> str:
    key = load_secret("OPENAI_API_KEY")
    if not key:
        raise VoiceUnavailable("Add OPENAI_API_KEY to ~/.odie/.env to use OpenAI voice.")
    return key


def get_voice(store: Store) -> str:
    v = (store.get_setting("voice") or {}).get("voice")
    return v if v in _VOICE_IDS else DEFAULT_VOICE


def set_voice(store: Store, v: str) -> str:
    """Talk's voice. Merged into the voice settings: replacing them dropped the read-aloud engine and its voices."""
    if v in _VOICE_IDS:
        s = dict(store.get_setting("voice") or {})
        s["voice"] = v
        store.set_setting("voice", s)
    return get_voice(store)


# OpenAI's speech can be slow on its own side: on 21 Oct 2026 gpt-4o-mini-tts took 40-50 s for a 2-second clip on about
# half the requests. So each try waits TTS_WAIT seconds, and a timeout or a busy answer is tried again after each pause.
TTS_WAIT = 120.0
RETRY_PAUSES = (2.0, 5.0)  # the pause before each retry: two retries, three tries in all


def try_again(error: Exception) -> bool:
    """Whether a failed OpenAI speech request is worth another try: a timeout, a dropped or refused connection, "too
    many requests" (429) or a server error (5xx) -> True; a wrong key (401), a bad request (400) -> False."""
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        return code == 429 or code >= 500
    return isinstance(error, (httpx.TimeoutException, httpx.TransportError))


async def tts(text: str, voice: str, key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
              fmt: str = "mp3", style: str = "") -> bytes:
    """OpenAI speech. `style` is how the voice should sound for this text (a video's own narration style); empty means
    Odie's usual tts_style. A slow or busy answer is tried again (try_again, RETRY_PAUSES); the last failure is raised."""
    instructions = style or tts_style(config.settings.country)
    body = {"model": tts_model(), "voice": voice, "input": text[:4000], "instructions": instructions, "response_format": fmt}
    headers = {"Authorization": f"Bearer {key or api_key()}"}
    for pause in (*RETRY_PAUSES, None):
        try:
            async with httpx.AsyncClient(timeout=TTS_WAIT, transport=transport) as c:
                r = await c.post(f"{API}/audio/speech", headers=headers, json=body)
                r.raise_for_status()
                return r.content
        except httpx.HTTPError as e:
            last_try = pause is None
            if last_try or not try_again(e):
                raise
            log.info("OpenAI speech didn't answer (%s); trying again in %.0f s", type(e).__name__, pause)
            await asyncio.sleep(pause)
    raise AssertionError("unreachable: the last try returns or raises")


async def stt(audio: bytes, filename: str, mime: str, key: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> str:
    async with httpx.AsyncClient(timeout=60, transport=transport) as c:
        r = await c.post(f"{API}/audio/transcriptions", headers={"Authorization": f"Bearer {key or api_key()}"},
                         data={"model": stt_model()}, files={"file": (filename, audio, mime)})
        r.raise_for_status()
        return (r.json().get("text") or "").strip()


def _have(caps: frozenset | None, cap: str) -> bool:
    return caps is None or cap in caps  # None: not known, so everything (as before)


def ask_tool(caps: frozenset | None = None) -> dict:
    """The one tool the voice model has: the brain, described by what this install can read."""
    reads = [w for w, cap in (("mail", "mail"), ("calendar", "calendar")) if _have(caps, cap)] + ["notes", "memory and the web"]
    return {
        "type": "function", "name": "ask_brain",
        "description": (f"Ask your own brain, which can read the user's {', '.join(reads)}, set reminders and "
                        "take actions (actions show them an approval card). Pass their request in their words, plus any detail from "
                        "this conversation it needs. Returns the answer as text for you to say."),
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
    }


ASK_TOOL = ask_tool()


def _topics(caps: frozenset | None) -> str:
    """What the voice model hands to the brain: this install's features, then what every install has."""
    have = [w for w, cap in (("mail", "mail"), ("calendar", "calendar"), ("bills", "money"), ("spending", "money")) if _have(caps, cap)]
    return ", ".join([*have, "notes", "reminders", "memory", "the news or the web"])


def realtime_instructions(name: str, soul: str | None, context: str, user: str = "", caps: frozenset | None = None) -> str:
    whose = f"{user}'s personal assistant" if user else "a personal assistant"
    persona = (soul or f"You are {name}, {whose}. Brief, warm, concrete.").strip()
    return (f"{persona}\n\nYou are talking with {user or 'the user'} by voice, as {name}. Speak naturally and briefly: one to three "
            "short sentences, no lists, no markdown, no reading out links or ids. Say amounts the way people say them.\n"
            f"For anything about their {_topics(caps)}, or any action, "
            "first say a few words like 'One moment', then call ask_brain with their request, then tell them the answer in your own "
            "words. Only act on what they clearly said; if you didn't catch it, ask them to repeat instead of guessing. "
            "Never guess personal facts. If ask_brain says something needs their approval, tell them a card is waiting in the app.\n\n"
            f"{context}")


async def dictation_session(key: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """A short-lived secret for live dictation: a transcription-only realtime session (no replies, no tools), so the
    phone sees the words while the user talks. Server VAD sends them phrase by phrase."""
    body = {"session": {
        "type": "transcription",
        "audio": {"input": {"noise_reduction": {"type": "near_field"},
                            "transcription": {"model": stt_model(), "language": "en",
                                              **({"prompt": p} if (p := transcription_prompt(config.settings.country)) else {})},
                            "turn_detection": {"type": "server_vad", "silence_duration_ms": 600}}}}}
    async with httpx.AsyncClient(timeout=20, transport=transport) as c:
        r = await c.post(f"{API}/realtime/client_secrets", headers={"Authorization": f"Bearer {key or api_key()}"}, json=body)
        r.raise_for_status()
        d = r.json()
    return {"client_secret": d["value"], "expires_at": d.get("expires_at")}


async def realtime_session(store: Store, context: str, soul: str | None = None, key: str | None = None,
                           transport: httpx.AsyncBaseTransport | None = None, caps: frozenset | None = None) -> dict:
    from odie import persona, profile
    name = persona.get(store)["name"]
    user = profile.get(store)["user_name"]
    v = get_voice(store)
    body = {"session": {
        "type": "realtime", "model": REALTIME_MODEL,
        "instructions": persona.apply_name(realtime_instructions(name, soul, context, user, caps), name),
        # Low eagerness + near-field noise reduction: a phone held close, and no turn taken on stray sound or its own echo.
        "audio": {"input": {"noise_reduction": {"type": "near_field"},
                            "transcription": {"model": stt_model(), "language": "en",
                                              **({"prompt": p} if (p := transcription_prompt(config.settings.country)) else {})},
                            "turn_detection": {"type": "semantic_vad", "eagerness": "low"}},
                  "output": {"voice": v}},
        "tools": [ask_tool(caps)], "tool_choice": "auto"}}
    async with httpx.AsyncClient(timeout=20, transport=transport) as c:
        r = await c.post(f"{API}/realtime/client_secrets", headers={"Authorization": f"Bearer {key or api_key()}"}, json=body)
        r.raise_for_status()
        d = r.json()
    return {"client_secret": d["value"], "expires_at": d.get("expires_at"), "model": REALTIME_MODEL, "voice": v, "name": name}
