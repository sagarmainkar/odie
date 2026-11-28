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
import sys

import httpx

from odie import config, machine, voice_libra, voice_url
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


# ── Read-aloud engines: OpenAI (cloud), Phonon (Ollama), and each speaking model on the voice server ──
# The voice server (odie/voice_url.py, normally voiced on :12000) loads a model when asked and unloads it when idle;
# Odie only asks it. Every speaking model it lists is an engine here, named as the server names it.
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
# What Odie knows before the server has been asked (a restart, a server that is down): the two models it ships with.
KNOWN_MODELS = [
    voice_url.Model("kokoro", "tts", KOKORO_VOICES, []),
    voice_url.Model("libra-tts", "tts", voice_libra.VOICES, voice_libra.TONES),
    voice_url.Model("parakeet", "stt"),
]
SERVER_NOTES = {
    "kokoro": "On your voice server. Fast and plain, no expressions.",
    "libra-tts": "On your voice server. Expressive: Odie picks the tone and laughs or sighs where it fits.",
    "orpheus": "On your voice server. Very natural English, a little slower to prepare.",
}
ENGINES = {
    "openai": {"label": "OpenAI", "note": "gpt-4o-mini-tts. Natural, quick, text goes to OpenAI.", "local": False},
    "phonon": {"label": "Phonon (Ollama)", "note": "On this computer through Ollama. Quick, streams, no expressions.", "local": True},
}
FIXED_ENGINES = frozenset(ENGINES)  # the rest of ENGINES is the voice server's models (learn_server_models)
_SERVER_MODELS: dict[str, voice_url.Model] = {}
_HEARING_MODELS: list[str] = []  # the server's hearing models (parakeet, whisper-base, …), in its order


def _label(name: str) -> str:
    """How a server model is named in Settings: "kokoro" -> "Kokoro"; "libra-tts" -> "Libra"."""
    return name.removesuffix("-tts").replace("-", " ").capitalize()


def learn_server_models(models: list[voice_url.Model]) -> None:
    """Makes the server's speaking models the engines after OpenAI and Phonon, in the server's order. A model named
    like a fixed engine is skipped. [kokoro (tts), parakeet (stt)] -> engines openai, phonon, kokoro."""
    _SERVER_MODELS.clear()
    _HEARING_MODELS.clear()
    for name in [k for k in ENGINES if k not in FIXED_ENGINES]:
        del ENGINES[name]
    for model in models:
        if model.kind == "stt":
            _HEARING_MODELS.append(model.name)
            continue
        if model.kind != "tts" or model.name in FIXED_ENGINES:
            continue
        _SERVER_MODELS[model.name] = _with_known_names(model)
        note = SERVER_NOTES.get(model.name, "On your voice server.")
        ENGINES[model.name] = {"label": _label(model.name), "note": note, "local": True}


def _with_known_names(model: voice_url.Model) -> voice_url.Model:
    """The model with the voices Odie already knows described as Odie knows them (Kokoro's af_heart is "Heart",
    American), so names in Settings, podcasts and a pinned video voice stay the same once the server is asked; a voice
    Odie doesn't know keeps the server's description. kokoro listing af_heart and af_new -> Heart, Af_new."""
    known = next((m for m in KNOWN_MODELS if m.name == model.name), None)
    if known is None:
        return model
    by_id = {v["id"]: v for v in known.voices}
    voices = [by_id.get(v["id"], v) for v in model.voices]
    return voice_url.Model(model.name, model.kind, voices, model.styles)


def forget_server_models() -> None:
    """Back to what Odie knows before asking the server (KNOWN_MODELS)."""
    learn_server_models(KNOWN_MODELS)


forget_server_models()
server_seen = False  # whether the voice server answered the last time Odie asked (learn_server)


async def learn_server_soon(store: Store, tries: int = 20, pause: float = 30.0) -> bool:
    """Asks the voice server for its models until it answers, `tries` times `pause` seconds apart (ten minutes by
    default): at login Odie can be up before voiced, and until it has asked, a chosen model it doesn't know (Orpheus,
    whisper-small) would be swapped for the default. Down twice, then up -> True after the third ask; never up -> False."""
    for attempt in range(tries):
        if await learn_server(store):
            return True
        if attempt < tries - 1:
            await asyncio.sleep(pause)
    return False


def hearing_models() -> list[str]:
    """The voice server's hearing models, in its order: ["parakeet", "whisper-base"]."""
    return list(_HEARING_MODELS)


def hearing(store: Store) -> tuple[str, str] | None:
    """Where dictation is heard: (the voice server's address, the hearing model), or None when the server has no
    hearing model. The model chosen in Settings while the server still has it, else Parakeet, else the server's first.
    Nothing chosen, server has parakeet -> (url, "parakeet"); "whisper-small" chosen and listed -> that; the server
    lists only whisper-base -> (url, "whisper-base")."""
    listed = hearing_models()
    if not listed:
        return None
    chosen = str(_voice_settings(store).get("hear_model") or "")
    if chosen in listed:
        return server_url(store), chosen
    if "parakeet" in listed:
        return server_url(store), "parakeet"
    return server_url(store), listed[0]


def set_hearing(store: Store, model: str) -> None:
    """Keeps the hearing model chosen in Settings (checked by the route first)."""
    s = _voice_settings(store)
    s["hear_model"] = model
    store.set_setting("voice", s)


async def hear(store: Store, audio: bytes, filename: str, mime: str,
               transport: httpx.AsyncBaseTransport | None = None) -> str:
    """The words in a recording, heard on the voice server. A server that isn't there, is slow, or can't read it is
    VoiceUnavailable, saying how to start it or what went wrong (the caller may try OpenAI instead)."""
    where = hearing(store)
    if where is None:
        raise VoiceUnavailable("The voice server has no hearing model.")
    url, model = where
    try:
        return await voice_url.transcribe(url, model, audio, filename, mime, transport=transport)
    except httpx.ConnectError:
        raise VoiceUnavailable(f"The voice server isn't answering at {url}: start it with `voiced start`.")
    except httpx.TimeoutException:
        raise VoiceUnavailable(f"The voice server at {url} took too long to answer.")
    except (httpx.HTTPError, ValueError) as e:
        raise VoiceUnavailable(f"The voice server couldn't hear it: {e}")


def is_server_engine(engine: str) -> bool:
    """Whether an engine is a model on the voice server: "kokoro" -> True; "phonon" -> False; "openai" -> False."""
    return engine in _SERVER_MODELS


def server_model(engine: str) -> voice_url.Model | None:
    return _SERVER_MODELS.get(engine)


def has_styles(engine: str) -> bool:
    """Whether an engine speaks in tones, so it hears the voice markup: "libra-tts" -> True; "kokoro" -> False."""
    model = _SERVER_MODELS.get(engine)
    return model is not None and bool(model.styles)


def migrated(s: dict) -> dict:
    """The voice settings in today's shape. Before 28 Nov 2026 Libra was its own engine on its own server (:8794, now
    retired) and Kokoro and Maya1 ran inside Odie; now they are models on the voice server. A dict already in today's
    shape comes back unchanged.
    {"engine": "libra", "libra_voice": "sofia", "libra_style": "wry"} -> engine "libra-tts", "libra-tts_voice" sofia,
    "server_style" wry; {"engine": "maya1"} -> engine "kokoro"; a libra_url other than :8794 becomes server_url."""
    moved = dict(s)
    if moved.get("engine") == "libra":
        moved["engine"] = "libra-tts"
    if moved.get("engine") == "maya1":
        moved["engine"] = "kokoro"
    if "libra_voice" in moved:
        moved.setdefault("libra-tts_voice", moved.pop("libra_voice"))
    if "libra_style" in moved:
        moved.setdefault("server_style", moved.pop("libra_style"))
    if "libra_speed" in moved:
        moved.setdefault("server_speed", moved.pop("libra_speed"))
    if "libra_url" in moved:
        old = voice_url.base(str(moved.pop("libra_url") or ""))
        if old and old != "http://127.0.0.1:8794":
            moved.setdefault("server_url", old)
    moved.pop("maya1_voice", None)
    return moved


def _voice_settings(store: Store) -> dict:
    return migrated(store.get_setting("voice") or {})


def server_url(store: Store) -> str:
    """The voice server's address: the one set in Settings, else voiced's own default (voice_url.DEFAULT_URL)."""
    chosen = str(_voice_settings(store).get("server_url") or "").strip()
    if not chosen:
        return voice_url.DEFAULT_URL
    return voice_url.base(chosen)


async def learn_server(store: Store, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Asks the voice server which models it has and makes them the engines. A server that doesn't answer leaves
    what Odie knew and returns False. Called at launch and each time Settings → Voice opens."""
    global server_seen
    try:
        listed = await voice_url.models(server_url(store), transport=transport)
    except (httpx.HTTPError, ValueError):
        server_seen = False
        return False
    server_seen = True
    learn_server_models(listed)
    return True


def disabled() -> set[str]:
    """The engines not offered on this machine: the voice server's models when no voice server is expected here (an
    Intel Mac, ODIE_VOICE=off, see odie.machine) and none has answered. Phonon runs in Ollama and OpenAI in the cloud,
    so they are offered everywhere. An M2 -> set(); an Intel Mac with nothing answering -> {"kokoro", "libra-tts"};
    an Intel Mac whose Settings point at a voice server on another Mac that answered -> set()."""
    if machine.local_voice_wanted() or server_seen:
        return set()
    return set(_SERVER_MODELS)


def default_engine() -> str:
    """The engine when none is chosen, or the chosen one isn't offered here: Phonon when Ollama had it the last time
    Odie asked (phonon_here), else Kokoro on the voice server where one is expected, else OpenAI (which needs its key;
    without one, read-aloud says so). Ollama with phonon, on any Mac -> "phonon"; no phonon, an M2 -> "kokoro"; no
    phonon, an Intel Mac -> "openai"."""
    if phonon_here():
        return "phonon"
    offered = [name for name in _SERVER_MODELS if name not in disabled()]
    if "kokoro" in offered:
        return "kokoro"
    if offered:
        return offered[0]
    return "openai"


def _chosen_engine(s: dict) -> str:
    """The engine the settings name, when it is offered here; else the default. {"engine": "kokoro"} on an M2 ->
    "kokoro"; the same on an Intel Mac with no voice server -> "openai"; {} -> the default."""
    engine = s.get("engine")
    if engine in ENGINES and engine not in disabled():
        return engine
    return default_engine()


_DEFAULT_VOICE = {"openai": DEFAULT_VOICE, "kokoro": "af_heart", "libra-tts": voice_libra.DEFAULT_VOICE}


def engine_voices(engine: str, store: Store | None = None) -> list[dict]:
    """An engine's voices. OpenAI's are a fixed list; a voice server model's are the ones the server described.
    Phonon's are the ones Ollama listed (phonon_voices), kept for the process, then, given the store, the ones the user
    found with "Another voice" (kept_voices); before Ollama has been asked, the one voice that always works, "default"."""
    if engine == "openai":
        return VOICES
    if engine != "phonon":
        model = _SERVER_MODELS.get(engine)
        return list(model.voices) if model is not None else []
    listed = list(_PHONON_VOICES.get(PHONON_MODEL) or [PHONON_DEFAULT])
    if store is None:
        return listed
    ids = {v["id"] for v in listed}
    return listed + [v for v in kept_voices(store) if v["id"] not in ids]


def default_voice(engine: str) -> str:
    """The voice an engine speaks in when none of its voices is chosen: Phonon's from what Ollama lists
    (default_phonon_voice), Kokoro's Heart, Libra's Nina, OpenAI's Marin, else the first voice the server listed.
    "kokoro" -> "af_heart"; "phonon" with Zoey listed -> "zoey"; "orpheus" listing tara first -> "tara"."""
    if engine == "phonon":
        return default_phonon_voice(engine_voices("phonon"))
    if engine in _DEFAULT_VOICE:
        return _DEFAULT_VOICE[engine]
    voices = engine_voices(engine)
    if voices:
        return voices[0]["id"]
    return ""


def voice_is_offered(engine: str, voice_id: str | None, store: Store | None = None) -> bool:
    """Whether a saved or asked-for voice can be used with this engine. OpenAI's are a fixed list, a server model's
    the ones it listed; a server model that lists none takes any name (the server says no if it's wrong). Phonon's
    are whatever Ollama listed; before Odie has asked Ollama (a restart), a saved Phonon voice is trusted, since Ollama
    is the one to say no (it answers 400, said plainly by phonon_tts). "af_heart" for kokoro -> True; "nova" for
    openai -> False; "easton" for phonon with Ollama's list read and Easton on it -> True; "easton" for phonon before
    the list is read -> True; "nobody" for phonon with the list read -> False; "anyone" for a model listing none -> True."""
    if not voice_id:
        return False
    if engine == "phonon" and PHONON_MODEL not in _PHONON_VOICES:
        return True
    voices = engine_voices(engine, store)
    if is_server_engine(engine) and not voices:
        return True
    return voice_id in {x["id"] for x in voices}


def _local_instead_of_openai() -> str | None:
    """The engine read-aloud uses when OpenAI is chosen but its key is gone: Phonon when Ollama has it, else Kokoro
    on the voice server where one is expected, else none (read-aloud then says the key is missing). Ollama with
    phonon -> "phonon"; an M2 without it -> "kokoro"; an Intel Mac without it -> None."""
    fallback = default_engine()
    if fallback == "openai":
        return None
    return fallback


def get_tts(store: Store) -> tuple[str, str]:
    """(engine, voice) for read-aloud. The realtime Talk voice is get_voice() (OpenAI only)."""
    s = _voice_settings(store)
    engine = _chosen_engine(s)
    if engine == "openai" and not load_secret("OPENAI_API_KEY"):
        engine = _local_instead_of_openai() or engine  # OpenAI voices need its key
    v = s.get("voice") if engine == "openai" else s.get(f"{engine}_voice")
    return engine, (v if voice_is_offered(engine, v, store) else default_voice(engine))


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
        for v in engine_voices(engine, store):
            if pinned in (v["id"], v["label"].lower()):
                return engine, v["id"]
    log.warning("video_voice %r isn't a voice offered here; videos speak in the read-aloud voice", pinned)
    return get_tts(store)


def set_tts(store: Store, engine: str | None = None, voice: str | None = None) -> tuple[str, str]:
    s = _voice_settings(store)
    if engine in ENGINES and engine not in disabled():
        s["engine"] = engine
    eng = _chosen_engine(s)  # the same default as get_tts
    if voice and voice_is_offered(eng, voice, store):
        s["voice" if eng == "openai" else f"{eng}_voice"] = voice
    store.set_setting("voice", s)
    return get_tts(store)


def set_server(store: Store, url: str | None = None, style: str | None = None, speed: str | None = None) -> None:
    """Keeps the voice server's address, the Settings tone and the speed (checked by the route first). An empty
    address goes back to the default; an empty tone means none: the voice then speaks plainly unless a reply names one."""
    s = _voice_settings(store)
    if url is not None:
        s["server_url"] = url
    if style is not None:
        s["server_style"] = style
    if speed is not None:
        s["server_speed"] = speed
    store.set_setting("voice", s)


def worker_wanted(store: Store) -> bool:
    """Whether read-aloud needs Odie's own voice worker: never any more, since read-aloud speaks through the voice
    server. The worker now runs only while Talk listens through it (/api/talk/listen), until Talk moves too."""
    return False


def worker_wanted_at_launch(store: Store) -> bool:
    """Whether Odie's own voice server starts at launch. Before Ollama has been asked, the default engine isn't known
    (Phonon may be there), so only an engine the user chose counts; _learn_phonon decides the rest once Ollama answers.
    Kokoro chosen -> True; Phonon chosen -> False; nothing chosen -> False (decided a moment later)."""
    chosen = (store.get_setting("voice") or {}).get("engine")
    if not chosen:
        return False
    return worker_wanted(store)


async def settle_worker(store: Store) -> None:
    """After the read-aloud engine changes: Odie's own voice server is stopped when read-aloud no longer uses it, so the
    process goes away. When it does use it, nothing happens now: the next speech starts it (local_tts asks the worker
    to be up first). Called by the async callers of set_tts, which is synchronous. A talk listening through the
    server (/api/talk/listen, hearing_streams) keeps it running. Phonon chosen, 1 stream open -> left running;
    Phonon chosen, 0 open -> stopped; Kokoro chosen -> left alone."""
    from odie import voice_worker
    worker = voice_worker.current
    if worker is None or worker_wanted(store):
        return
    if hearing_streams > 0:
        return  # a talk is listening through it (/api/talk/listen): the next settle, or Odie's exit, stops it
    await worker.stop()


def local_url() -> str:
    """Odie's own voice worker (odie.voice_worker), on its own port: used now only for Talk's listening."""
    from odie.voice_worker import voice_port
    return f"http://127.0.0.1:{voice_port()}"


# ── Hearing: the voice worker's /stt/stream, passed through by /api/talk/listen (odie/app/routes.py) ──
hearing_streams = 0  # listen streams open now; settle_worker never stops the worker while one is open


def hearing_url() -> str:
    """The voice worker's live-hearing WebSocket: "ws://127.0.0.1:8771/stt/stream" on the default port."""
    return local_url().replace("http://", "ws://", 1) + "/stt/stream"


async def _health_hearing(url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> bool | None:
    """What the voice server's /health says about hearing, in one quick GET; None when nothing answers there.
    {"hearing": true} -> True; {"hearing": false}, an older server without the field, or a broken answer -> False;
    nothing on the port -> None."""
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as c:
            r = await c.get(f"{url}/health")
    except httpx.HTTPError:
        return None
    try:
        return r.status_code == 200 and r.json().get("hearing") is True
    except (ValueError, AttributeError):
        return False


async def hearing_available(transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Whether a paired app can listen through Odie (/api/talk/listen). The worker is normally stopped (read-aloud uses
    Phonon), and the listen starts it, so being set up is enough until it runs; once it runs, its /health decides.
    One GET with a short timeout, so a hung worker never holds up /api/health (the Mac waits 2 s for it).
    Running and its /health says hearing -> True; running without the hearing models -> False; set up and stopped ->
    True; never set up and stopped -> False; no worker at all (ODIE_VOICE=off) -> False: whatever answers on the port
    is someone else's service, never asked."""
    from odie import voice_worker
    worker = voice_worker.current
    if worker is None:
        return False
    answer = await _health_hearing(worker.url, 0.5, transport)
    if answer is None:
        return bool(worker.installed)  # stopped: the listen starts it
    return answer


async def speak(store: Store, text: str, engine: str | None = None, voice: str | None = None,
                tone: str | None = None) -> tuple[bytes, str]:
    """Read-aloud with the chosen engine. Returns (audio, media type). A voice server model with styles hears the
    reply's voice markup (its tone, or `tone` when the caller passes the reply's tone with one sentence of it); every
    other engine gets it stripped. A voice server that doesn't answer hands over to instead_of_server."""
    eng, v = get_tts(store)
    eng, v = engine or eng, voice or v
    if is_server_engine(eng):
        try:
            return await server_tts(store, text, eng, v, tone=tone), "audio/wav"
        except VoiceUnavailable as e:
            eng, v = instead_of_server(store, e)
    text = voice_libra.hidden(text)
    if eng == "openai":
        return await tts(text, v), "audio/mpeg"
    return await phonon_tts(text, v), "audio/wav"


async def speak_wav(store: Store, text: str, voice: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                    engine: str | None = None, style: str = "") -> bytes:
    """`text` as a 16-bit WAV in the chosen engine (a voice memo, a podcast's turn). OpenAI is asked for raw PCM, so
    every engine's audio joins alike. `engine` with `voice` speaks in that engine instead (a video's own voice,
    video_tts). `style` steers an OpenAI voice for this text (tts); the others never see it."""
    from odie.media import pcm_to_wav
    eng, v = get_tts(store)
    if engine and voice:
        eng, v = engine, voice
    if is_server_engine(eng):
        try:
            return await server_tts(store, text, eng, voice or v, transport=transport)
        except VoiceUnavailable:
            if voice:
                raise  # a voice asked for by name (a podcast host, a video's voice): another engine can't be it
            eng, v = instead_of_server(store, sys.exc_info()[1])
    text = voice_libra.hidden(text)
    if eng == "openai":
        return pcm_to_wav(await tts(text, voice or v, transport=transport, fmt="pcm", style=style))
    return await phonon_tts(text, voice or v, transport=transport)


def instead_of_server(store: Store, problem: VoiceUnavailable) -> tuple[str, str]:
    """The engine and voice used when the voice server can't speak, so speech never goes silent: Phonon when Ollama
    has it, else OpenAI with its key, each in the voice chosen for it in Settings (else its default); with neither,
    the problem is raised as it was. The log says why.
    Phonon in Ollama, Harper chosen for it -> ("phonon", "Harper"); no Phonon, an OpenAI key -> ("openai", "marin")."""
    if phonon_here():
        engine = "phonon"
    elif load_secret("OPENAI_API_KEY"):
        engine = "openai"
    else:
        raise problem
    log.warning("%s Speaking with %s instead.", problem, engine)
    s = _voice_settings(store)
    chosen = s.get("voice") if engine == "openai" else s.get(f"{engine}_voice")
    if voice_is_offered(engine, chosen, store):
        return engine, chosen
    return engine, default_voice(engine)


async def server_tts(store: Store, text: str, engine: str, voice: str, tone: str | None = None,
                     speed: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """`text` spoken by the voice server's model `engine` in `voice`, as a WAV. A model with styles (Libra) gets the
    tone the text or the caller asks for (tone_to_use), its sound tags performed, silent ends trimmed, and is played
    at `speed` (else the Settings speed); any other model gets plain text. A server that doesn't answer or refuses is
    VoiceUnavailable, saying where Odie looked and how to start it."""
    settings = _voice_settings(store)
    url = server_url(store)
    styled = has_styles(engine)
    if styled:
        spoken = voice_libra.for_libra(text)
        style = voice_libra.tone_to_use(tone, text, settings)
        extra = {"trim": True}
    else:
        spoken = voice_libra.hidden(text)
        style = None
        extra = {}
    if not voice_libra.has_words(spoken):
        raise VoiceUnavailable("There's nothing to say once the voice markup is taken out.")
    try:
        wav = await voice_url.speak(url, engine, voice, spoken, style=style, extra=extra, transport=transport)
    except httpx.ConnectError:
        raise VoiceUnavailable(f"The voice server isn't answering at {url}: start it with `voiced start`.")
    except httpx.TimeoutException:
        raise VoiceUnavailable(f"The voice server at {url} took too long to answer.")
    except ValueError as e:
        raise VoiceUnavailable(f"The voice server refused it: {e}")
    except httpx.HTTPError as e:  # up but failing: a 5xx (a model that won't load), a dropped connection
        raise VoiceUnavailable(f"The voice server at {url} couldn't speak it: {type(e).__name__}")
    if not styled:
        return wav
    if speed is None:
        speed = voice_libra.settings_speed(settings)
    return await voice_libra.quicken(wav, speed)


def styles_on(store: Store) -> bool:
    """Whether read-aloud speaks with a model that has styles, so the chat model is told about the voice markup (the
    libra_voice capability). Libra chosen -> True; Kokoro chosen -> False; Phonon chosen -> False."""
    engine, _ = get_tts(store)
    return has_styles(engine)


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
    """Whether Ollama had a phonon model the last time Odie asked (phonon_available); False before it has asked.
    Asked, Ollama had phonon:latest -> True; asked, Ollama had only gemma -> False; not asked yet -> False."""
    return _PHONON_SEEN.get("here", False)


def voice_label(name: str) -> str:
    """How a voice name Ollama lists is shown: capitalised when Ollama spells it all lower-case, else as Ollama spells
    it. "zoey" -> "Zoey"; "Captain Silas Blackwater" -> as it is; "ZOEY" -> as it is."""
    if name == name.lower():
        return name.capitalize()
    return name


def phonon_voice(name: str) -> dict:
    """One voice Ollama lists, as the picker shows it: its group, a short note and its gender from the catalogue
    (odie.voice_phonon). "zoey" -> {"id": "zoey", "label": "Zoey", "group": "American · Female", "note": "Playful…",
    "gender": "female"}."""
    from odie import voice_phonon
    return {"id": name, "label": voice_label(name), **voice_phonon.describe(name)}


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
    from odie import voice_phonon
    named = [phonon_voice(n) for n in names if n.lower() != "default"]  # "default" is never shown as a choice
    listed = voice_phonon.ordered(named) or [dict(PHONON_DEFAULT)]
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
    return [model_name(m) for m in models if isinstance(m, dict)]


def model_name(entry: dict) -> str:
    """A model's name in Ollama's /api/tags list: "name", or "model" in older Ollamas that only send that."""
    name = entry.get("name")
    if not name:
        name = entry.get("model", "")
    return str(name)


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


def phonon_problem(status: int, body: str, voice_id: str, model: str = "phonon") -> str:
    """What to tell the user when Ollama refuses a Phonon request: the model isn't pulled (the pull command names that
    model), the voice isn't one Phonon has, or Ollama's own words. 404 "model \"phonon\" not found" -> PULL_PHONON;
    the same for a kept voice of phonon:fr -> "Ollama doesn't have phonon:fr: run `ollama pull phonon:fr`…";
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
        if model == PHONON_MODEL:
            return PULL_PHONON
        return f"Ollama doesn't have {model}: run `ollama pull {model}`, then try again."
    return f"Ollama couldn't speak that ({status}): {said[:160]}"


async def _phonon_piece(client: httpx.AsyncClient, text: str, voice_id: str, model: str) -> bytes:
    """One request to Ollama's speech route; the WAV bytes, or VoiceUnavailable with a reason a person can act on."""
    body = {"model": model, "input": text, "voice": voice_id, "response_format": "wav"}
    try:
        r = await client.post(f"{ollama_root()}/v1/audio/speech", json=body)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise VoiceUnavailable(f"Ollama isn't answering at {ollama_root()}: start Ollama, then try again.") from e
    if r.status_code != 200:
        raise VoiceUnavailable(phonon_problem(r.status_code, r.text, voice_id, model))
    return r.content


async def phonon_tts(text: str, voice_id: str, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """`text` spoken by Phonon through Ollama as one WAV, through the model the voice belongs to (speaker_of): long
    text in sentence-sized pieces (split_for_phonon), asked one after another, joined (join_wavs). Nothing leaves this
    computer but the request to Ollama."""
    model, name = speaker_of(voice_id)
    wavs = []
    async with httpx.AsyncClient(timeout=300, transport=transport) as c:
        for piece in split_for_phonon(text):
            wavs.append(await _phonon_piece(c, piece, name, model))
    return join_wavs(wavs)


# ── "Another voice": a name the user types, checked against the Phonon models Ollama has, then kept ──
NAME_LIMIT = 80
CHECK_LINE = "Hello, this is how I sound."
NO_SUCH_VOICE = ('No Phonon model here has a voice called "{name}". French, German, Spanish and Portuguese voices need '
                 "another Phonon model, for example: ollama pull phonon:fr")
_KEPT_ID = re.compile(r"^(?P<name>.+) \((?P<model>phonon[^()]*)\)$")


def speaker_of(voice_id: str) -> tuple[str, str]:
    """Which model a voice id speaks through, and the voice's own name. A kept voice from another Phonon model carries
    the model in brackets; any other id is a voice of `phonon` itself. "Noémie (phonon:fr)" -> ("phonon:fr",
    "Noémie"); "Zoey" -> ("phonon", "Zoey"); "Captain Silas Blackwater" -> ("phonon", "Captain Silas Blackwater")."""
    found = _KEPT_ID.match(voice_id)
    if found is None:
        return PHONON_MODEL, voice_id
    return found.group("model"), found.group("name")


def kept_voice_id(name: str, model: str) -> str:
    """The id a kept voice gets: its name when `phonon` speaks it, else the name with its model in brackets, so speaking
    knows where to send it (speaker_of). ("Ziggy", "phonon") -> "Ziggy"; ("Noémie", "phonon:fr") -> "Noémie
    (phonon:fr)"."""
    if model == PHONON_MODEL:
        return name
    return f"{name} ({model})"


def typed_name_problem(name: str) -> str | None:
    """Whether a typed name is worth asking Ollama about: None when it is, else what's wrong. Empty or blank -> "Type a
    voice name first."; over 80 characters -> "That name is too long: 80 characters at most."; "Noémie" -> None."""
    typed = (name or "").strip()
    if not typed:
        return "Type a voice name first."
    if len(typed) > NAME_LIMIT:
        return f"That name is too long: {NAME_LIMIT} characters at most."
    return None


def models_to_try(installed: list[str]) -> list[str]:
    """The Phonon models a typed name is tried against, in order: `phonon` first, then every other Phonon model Ollama
    has (`phonon:latest` is `phonon` again). ["phonon:latest", "phonon:fr"] -> ["phonon", "phonon:fr"]; [] ->
    ["phonon"]."""
    others = [m for m in installed if m not in (PHONON_MODEL, f"{PHONON_MODEL}:latest")]
    return [PHONON_MODEL, *others]


def kept_voices(store: Store) -> list[dict]:
    """The voices the user found with "Another voice", as the picker shows them, under "Your voices"."""
    from odie import voice_phonon
    kept = (store.get_setting("voice") or {}).get("phonon_extra") or []
    out = []
    for item in kept:
        name = str(item.get("name") or "")
        model = str(item.get("model") or PHONON_MODEL)
        if not name:
            continue
        out.append({"id": kept_voice_id(name, model), "label": name, "group": voice_phonon.YOURS, "note": f"through {model}",
                    "gender": None, "kept": True})
    return out


def keep_phonon_voice(store: Store, name: str, model: str) -> str:
    """Keeps a voice the check found: listed under "Your voices", and the chosen read-aloud voice from now on."""
    s = dict(store.get_setting("voice") or {})
    kept = [k for k in (s.get("phonon_extra") or []) if not (k.get("name") == name and k.get("model") == model)]
    s["phonon_extra"] = [*kept, {"name": name, "model": model}]
    voice_id = kept_voice_id(name, model)
    s["engine"] = "phonon"
    s["phonon_voice"] = voice_id
    store.set_setting("voice", s)
    return voice_id


def forget_phonon_voice(store: Store, voice_id: str) -> None:
    """Removes a kept voice; when it was the chosen one, read-aloud goes back to Phonon's default voice."""
    s = dict(store.get_setting("voice") or {})
    remaining = []
    for item in s.get("phonon_extra") or []:
        item_id = kept_voice_id(str(item.get("name", "")), str(item.get("model", PHONON_MODEL)))
        if item_id != voice_id:
            remaining.append(item)
    s["phonon_extra"] = remaining
    if s.get("phonon_voice") == voice_id:
        s.pop("phonon_voice")
    store.set_setting("voice", s)


async def _try_voice(client: httpx.AsyncClient, model: str, name: str) -> bytes | None:
    """One short line in this voice from this model: the WAV, or None when the model doesn't have the voice (400) or
    isn't pulled (404). Anything else is a problem with Ollama itself, said plainly."""
    body = {"model": model, "input": CHECK_LINE, "voice": name, "response_format": "wav"}
    try:
        r = await client.post(f"{ollama_root()}/v1/audio/speech", json=body)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise VoiceUnavailable(f"Ollama isn't answering at {ollama_root()}: start Ollama, then try again.") from e
    if r.status_code in (400, 404):
        return None
    if r.status_code != 200:
        raise VoiceUnavailable(phonon_problem(r.status_code, r.text, name, model))
    return r.content


def listed_phonon_voice(typed: str) -> str | None:
    """Whether a typed name is a voice Ollama already lists for `phonon` (Ollama matches names in any case), and its
    listed id. Listed "Zoey": "zoey" -> "Zoey", "ZOEY" -> "Zoey"; "Noémie" -> None (worth asking the other models)."""
    wanted = typed.lower()
    for v in engine_voices("phonon"):
        if v["id"].lower() == wanted:
            return v["id"]
    return None


async def check_phonon_voice(store: Store, name: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """"Another voice": tries a typed name against `phonon`, then each other Phonon model Ollama has (models_to_try),
    with one short line. The first model that speaks it wins: the voice is kept and chosen, and {"id", "audio"} comes
    back (the audio is its preview). A name Ollama already lists is simply chosen: {"id": the listed id, "audio": None}
    and nothing is kept (listed_phonon_voice). ValueError, in words a person can act on, when the name isn't worth
    asking (typed_name_problem) or no model has the voice (NO_SUCH_VOICE); nothing is kept then."""
    problem = typed_name_problem(name)
    if problem:
        raise ValueError(problem)
    typed = name.strip()
    listed = listed_phonon_voice(typed)
    if listed is not None:
        set_tts(store, "phonon", listed)
        return {"id": listed, "audio": None}
    installed = await phonon_models(transport)
    async with httpx.AsyncClient(timeout=120, transport=transport) as c:
        for model in models_to_try(installed):
            audio = await _try_voice(c, model, typed)
            if audio is None:
                continue
            voice_id = keep_phonon_voice(store, typed, model)
            return {"id": voice_id, "audio": join_wavs([audio])}
    raise ValueError(NO_SUCH_VOICE.format(name=typed))


_PAIRS = {"a": ("af_heart", "am_michael"), "b": ("bf_emma", "bm_george"), "h": ("hf_alpha", "hm_omega")}


def _one_of(voices: list[dict], gender: str, preferred: str) -> dict | None:
    """A voice of this gender from the list: the preferred name when it's there, else the first; None when there's none.
    [zoey, Maeve, easton], "female", "zoey" -> zoey; [Maeve, easton], "female", "zoey" -> Maeve; [easton], "female" -> None."""
    pool = [v for v in voices if v.get("gender") == gender]
    for v in pool:
        if v["id"].lower() == preferred:
            return v
    return pool[0] if pool else None


def phonon_hosts(voices: list[dict], chosen: str) -> list[dict]:
    """A podcast's two hosts when Phonon speaks, [a woman, a man] as with the other engines, from the voices Ollama lists
    and the catalogue's genders: the chosen voice is one of them, the other is Zoey or Easton when listed, else the first
    of that gender. A chosen character or unknown voice comes first, with another listed voice after it.
    [zoey, easton, Maeve, Alfie]: Alfie chosen -> [zoey, Alfie]; Maeve chosen -> [Maeve, easton];
    Captain Silas Blackwater chosen -> [Captain Silas Blackwater, zoey]; only "default" -> [default, default]."""
    by_id = {v["id"]: v for v in voices}
    first = by_id.get(chosen)
    if first is None:
        first = voices[0] if voices else dict(PHONON_DEFAULT)
    others = [v for v in voices if v["id"] != first["id"]]
    anyone = others[0] if others else first  # when no voice of the wanted gender is listed

    def partner(gender: str, preferred: str) -> dict:
        found = _one_of(others, gender, preferred)
        return found if found is not None else anyone
    if first.get("gender") == "female":
        return [first, partner("male", "easton")]
    if first.get("gender") == "male":
        return [partner("female", "zoey"), first]
    return [first, partner("female", "zoey")]


def server_hosts(voices: list[dict], chosen: str) -> list[dict]:
    """A podcast's two hosts on a voice server model, [a woman, a man]: the chosen voice in its own place, the first
    of the other gender in the other; with no one of a gender, the first voice listed.
    Libra, Sofia chosen -> [Sofia, Omar]; Jon chosen -> [Nina, Jon]; an unknown id -> [Nina, Omar]."""
    if not voices:
        nobody = {"id": chosen, "label": chosen.capitalize(), "group": ""}
        return [nobody, nobody]
    women = [v for v in voices if v.get("group") == "female"]
    men = [v for v in voices if v.get("group") == "male"]
    woman = women[0] if women else voices[0]
    man = men[0] if men else voices[0]
    picked = next((v for v in voices if v["id"] == chosen), None)
    if picked is not None and picked.get("group") == "female":
        woman = picked
    if picked is not None and picked.get("group") == "male":
        man = picked
    return [woman, man]


def _kokoro_lang(voice: dict) -> str:
    """Kokoro's accent letter, from its voice id: "bf_emma" -> "b"; "hm_omega" -> "h"."""
    return voice.get("lang") or voice["id"][:1]


def podcast_voices(store: Store) -> list[dict]:
    """A podcast's two hosts, [a woman, a man], from the chosen engine and with the chosen voice's accent; the chosen
    voice is one of them. Phonon's two come from the voices Ollama lists (phonon_hosts); a voice server model other
    than Kokoro's from the voices it lists (server_hosts)."""
    eng, v = get_tts(store)
    if eng == "phonon":
        return phonon_hosts(engine_voices("phonon", store), v)
    if eng not in ("openai", "kokoro"):
        return server_hosts(engine_voices(eng), v)
    voices = {x["id"]: x for x in engine_voices(eng)}
    if v not in voices:
        return server_hosts(list(voices.values()), v)
    chosen = voices[v]
    woman, man = ("marin", "cedar") if eng == "openai" else _PAIRS.get(_kokoro_lang(chosen), _PAIRS["a"])
    if chosen["group"] == "female":
        woman = v
    elif chosen["group"] == "male":
        man = v
    if woman not in voices or man not in voices:
        return server_hosts(list(voices.values()), v)
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
    for v in engine_voices(engine, store):
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
