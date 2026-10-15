"""Voice through OpenAI: read-aloud (gpt-4o-mini-tts), dictation (gpt-4o-mini-transcribe) and realtime talk
(gpt-realtime-2.1-mini over WebRTC). The API key stays on this computer; the phone only ever gets a short-lived
realtime client secret.

Realtime design: the voice model handles the conversation itself, but anything about the user's world (mail,
calendar, money, notes, reminders, memory, web, actions) goes through ONE tool, ask_brain, which runs a normal
Odie turn (Gemma, all tools, approvals, memory). So OpenAI sees the spoken conversation, not raw mail or ledger
data, and every real action still gets an approval card."""
from __future__ import annotations

import httpx

from odie import config
from odie.secrets import load_secret
from odie.store.db import Store

API = "https://api.openai.com/v1"
TTS_MODEL = "gpt-4o-mini-tts"
STT_MODEL = "gpt-4o-mini-transcribe"
REALTIME_MODEL = "gpt-realtime-2.1-mini"
DEFAULT_VOICE = "marin"
# Voices that work for BOTH read-aloud and realtime (checked against the API on 2026-10-01), so one choice covers both.
# Grouped by how they usually sound (OpenAI doesn't label voices by gender; this is a listening guide, not a fact).
_GROUPS = {"female": ["marin", "coral", "sage", "shimmer"], "male": ["cedar", "ash", "ballad", "echo", "verse"], "neutral": ["alloy"]}
VOICES = [{"id": v, "label": v.capitalize(), "group": g} for g, ids in _GROUPS.items() for v in ids]
_VOICE_IDS = {v["id"] for v in VOICES}
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
}
# Maya1 is hidden until its pipeline is rebuilt from the official prompt format (2026-10-01: through mlx-audio's generic
# loader it read tags out as words or produced noise).
DISABLED = {"maya1"}
_ENGINE_VOICES = {"openai": VOICES, "kokoro": KOKORO_VOICES, "maya1": MAYA_VOICES}
_DEFAULT_VOICE = {"openai": DEFAULT_VOICE, "kokoro": "af_heart", "maya1": "in_female"}


def engine_voices(engine: str) -> list[dict]:
    return _ENGINE_VOICES.get(engine, [])


def get_tts(store: Store) -> tuple[str, str]:
    """(engine, voice) for read-aloud. The realtime Talk voice is get_voice() (OpenAI only)."""
    s = store.get_setting("voice") or {}
    engine = s.get("engine") if s.get("engine") in ENGINES and s.get("engine") not in DISABLED else "kokoro"
    if engine == "openai" and not load_secret("OPENAI_API_KEY"):
        engine = "kokoro"  # Kokoro is the default; OpenAI voices need its key
    v = s.get("voice") if engine == "openai" else s.get(f"{engine}_voice")
    ids = {x["id"] for x in engine_voices(engine)}
    return engine, (v if v in ids else _DEFAULT_VOICE[engine])


def set_tts(store: Store, engine: str | None = None, voice: str | None = None) -> tuple[str, str]:
    s = dict(store.get_setting("voice") or {})
    if engine in ENGINES and engine not in DISABLED:
        s["engine"] = engine
    eng = s.get("engine") if s.get("engine") in ENGINES and s.get("engine") not in DISABLED else "kokoro"  # same default as get_tts
    if voice and voice in {x["id"] for x in engine_voices(eng)}:
        s["voice" if eng == "openai" else f"{eng}_voice"] = voice
    store.set_setting("voice", s)
    return get_tts(store)


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


async def speak_wav(store: Store, text: str, voice: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """`text` as a 16-bit WAV in the chosen engine (a voice memo, a podcast's turn). OpenAI is asked for raw PCM, so
    both engines' audio joins alike."""
    from odie.media import pcm_to_wav
    eng, v = get_tts(store)
    if eng == "openai":
        return pcm_to_wav(await tts(text, voice or v, transport=transport, fmt="pcm"))
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


_PAIRS = {"a": ("af_heart", "am_michael"), "b": ("bf_emma", "bm_george"), "h": ("hf_alpha", "hm_omega")}


def podcast_voices(store: Store) -> list[dict]:
    """A podcast's two hosts, [a woman, a man], from the chosen engine and with the chosen voice's accent; the chosen
    voice is one of them."""
    eng, v = get_tts(store)
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


async def tts(text: str, voice: str, key: str | None = None, transport: httpx.AsyncBaseTransport | None = None, fmt: str = "mp3") -> bytes:
    async with httpx.AsyncClient(timeout=60, transport=transport) as c:
        r = await c.post(f"{API}/audio/speech", headers={"Authorization": f"Bearer {key or api_key()}"},
                         json={"model": TTS_MODEL, "voice": voice, "input": text[:4000], "instructions": tts_style(config.settings.country), "response_format": fmt})
        r.raise_for_status()
        return r.content


async def stt(audio: bytes, filename: str, mime: str, key: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> str:
    async with httpx.AsyncClient(timeout=60, transport=transport) as c:
        r = await c.post(f"{API}/audio/transcriptions", headers={"Authorization": f"Bearer {key or api_key()}"},
                         data={"model": STT_MODEL}, files={"file": (filename, audio, mime)})
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
                            "transcription": {"model": STT_MODEL, "language": "en",
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
                            "transcription": {"model": STT_MODEL, "language": "en",
                                              **({"prompt": p} if (p := transcription_prompt(config.settings.country)) else {})},
                            "turn_detection": {"type": "semantic_vad", "eagerness": "low"}},
                  "output": {"voice": v}},
        "tools": [ask_tool(caps)], "tool_choice": "auto"}}
    async with httpx.AsyncClient(timeout=20, transport=transport) as c:
        r = await c.post(f"{API}/realtime/client_secrets", headers={"Authorization": f"Bearer {key or api_key()}"}, json=body)
        r.raise_for_status()
        d = r.json()
    return {"client_secret": d["value"], "expires_at": d.get("expires_at"), "model": REALTIME_MODEL, "voice": v, "name": name}
