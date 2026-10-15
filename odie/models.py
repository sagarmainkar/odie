"""Model providers and selection. Every provider speaks the OpenAI chat-completions API.
One model for everything (the agent, the brief, memory review, summaries, background checks): the "chat" selection."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx

from odie import config
from odie.secrets import load_secret
from odie.store.db import Store

log = logging.getLogger(__name__)

EMBEDDING_RE = re.compile(r"embed|rerank|whisper|tts|bge|\bgte\b|minilm|e5-|dall-e|image|moderation|realtime|transcribe|"
                          r"audio|sora|davinci|babbage", re.I)  # not chat models


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    api_key: str | None
    local: bool                 # runs on this machine: prompts never leave this computer


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    base_url: str        # the provider's own address; <ID>_BASE_URL in ~/.odie/.env replaces it (preset_base_url)
    env: str             # the key's name in the .env file
    window: int          # context size to assume when the provider can't say (every current chat model has at least this)
    default_model: str   # the model Odie falls back to when nothing is chosen and this is the first provider available


# Cloud providers the user can switch on with just a key. All speak the OpenAI chat-completions API.
PRESETS = [
    Preset("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY", 128_000, "gpt-5.5"),
    Preset("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", 128_000,
           "anthropic/claude-sonnet-5-5"),
    Preset("gemini", "Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", 128_000,
           "gemini-3-pro"),
    Preset("anthropic", "Claude", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", 200_000, "claude-sonnet-5-5"),
]
PRESET_BY_ID = {p.id: p for p in PRESETS}

OLLAMA_BASE_URL = "http://localhost:11434/v1"

# The .env setting that moves each built-in provider to another address (another computer, a proxy). Custom providers
# carry their own address, set in Settings → Providers.
BASE_URL_ENV = {
    "lmstudio": "LM_STUDIO_BASE_URL",
    "ollama": "OLLAMA_BASE_URL",
    "openai": "OPENAI_BASE_URL",
    "openrouter": "OPENROUTER_BASE_URL",
    "gemini": "GEMINI_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
}


def provider_base_url(provider_id: str, default: str) -> str:
    """A built-in provider's address: its <ID>_BASE_URL (from the environment, else ~/.odie/.env) when set, else
    `default`. Read on every call, so an edited .env is used from the next request without a restart.
      OLLAMA_BASE_URL=http://studio.local:11434/v1/  ->  provider_base_url("ollama", "http://localhost:11434/v1")
                                                         == "http://studio.local:11434/v1"   (a trailing / is dropped)
      nothing set                                     ->  "http://localhost:11434/v1"         (the default)"""
    env_name = BASE_URL_ENV[provider_id]
    override = load_secret(env_name)
    if not override:
        return default
    return override.rstrip("/")


def preset_base_url(preset: Preset) -> str:
    """A cloud preset's address, with its .env override. Odie lists Claude's models and checks its key on the
    OpenAI-style /v1 address, while ANTHROPIC_BASE_URL may be written as the anthropic library takes it (the root,
    no /v1), so Claude's gets /v1 added when it's missing."""
    url = provider_base_url(preset.id, preset.base_url)
    if preset.id == "anthropic" and not url.endswith("/v1"):
        url = url + "/v1"
    return url


def local_providers() -> list[Provider]:
    lm_studio_url = provider_base_url("lmstudio", config.settings.lm_studio_base_url)
    ollama_url = provider_base_url("ollama", OLLAMA_BASE_URL)
    return [
        Provider("lmstudio", "LM Studio", lm_studio_url, config.settings.lm_studio_api_key, True),
        Provider("ollama", "Ollama", ollama_url, None, True),
    ]


def keyed_presets() -> list[Preset]:
    """The cloud presets that have a key, in PRESETS order."""
    return [p for p in PRESETS if load_secret(p.env)]


def default_providers() -> list[Provider]:
    """The two on this computer, plus each cloud preset that has a key."""
    out = local_providers()
    for p in keyed_presets():
        key = load_secret(p.env)
        out.append(Provider(p.id, p.name, preset_base_url(p), key, False))
    return out


def custom_key_name(pid: str) -> str:
    return "ODIE_PROVIDER_" + re.sub(r"[^A-Z0-9]+", "_", pid.upper()).strip("_") + "_KEY"


def custom_providers(store: Store) -> list[Provider]:
    out = []
    for p in store.get_setting("providers.custom", []) or []:
        key = p.get("api_key") or load_secret(custom_key_name(p["id"]))  # older settings kept the key inline
        out.append(Provider(p["id"], p.get("name") or p["id"], p["base_url"].rstrip("/"), key or None, False))
    return out


def all_providers(store: Store) -> list[Provider]:
    return default_providers() + custom_providers(store)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "custom"


def auth_headers(p: Provider) -> dict:
    if not p.api_key:
        return {}
    h = {"Authorization": f"Bearer {p.api_key}"}
    if p.id == "anthropic":  # its model list wants its own headers; chat works with Bearer
        h |= {"x-api-key": p.api_key, "anthropic-version": "2023-06-01"}
    return h


async def _models_of(c: httpx.AsyncClient, p: Provider) -> list[dict]:
    r = await c.get(p.base_url + "/models", headers=auth_headers(p))
    r.raise_for_status()
    return r.json().get("data", [])


async def list_models(providers: list[Provider], transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    async with httpx.AsyncClient(timeout=8, transport=transport) as c:
        async def one(p: Provider) -> dict:
            entry = {"id": p.id, "name": p.name, "local": p.local, "models": [], "error": None,
                     "base_url": p.base_url, "base_url_env": BASE_URL_ENV.get(p.id)}  # a custom provider's has none
            try:
                for m in await _models_of(c, p):
                    mid = (m.get("id") or "").removeprefix("models/")  # Gemini lists "models/gemini-…"
                    if not mid or EMBEDDING_RE.search(mid):
                        continue
                    entry["models"].append({"id": mid, "local": p.local and not mid.endswith(("-cloud", ":cloud"))})
            except Exception as e:  # noqa: BLE001
                entry["error"] = f"{type(e).__name__}"
            return entry
        return list(await asyncio.gather(*(one(p) for p in providers)))


@dataclass(frozen=True)
class Selection:
    provider: Provider
    model: str
    slot: str

    @property
    def leaves_mini(self) -> bool:
        return (not self.provider.local) or self.model.endswith(("-cloud", ":cloud"))


def resolve_selection(store: Store, slot: str = "chat") -> Selection:
    """The chosen model. One model does everything, so every slot is the chat one; an older install's saved
    "model.jobs" is ignored. Nothing chosen (or its provider is gone): the fallback refresh_fallback() picked, else
    LM Studio with the configured model. Never touches the network: it runs on every turn."""
    providers = {p.id: p for p in all_providers(store)}
    chosen = store.get_setting("model.chat")
    if chosen and chosen.get("provider") in providers:
        return Selection(providers[chosen["provider"]], chosen["model"], "chat")
    fallback = store.get_setting(FALLBACK_SETTING)
    if fallback and fallback.get("provider") in providers:
        return Selection(providers[fallback["provider"]], fallback["model"], "chat")
    return Selection(providers["lmstudio"], config.settings.model_id, "chat")


def brain_chosen(store: Store) -> bool:
    """Whether Odie has a brain someone (or the fallback check) actually picked, rather than the built-in default it
    falls back to on a fresh install. Example: a model chosen in Settings or Setup -> True; the fallback check found
    LM Studio answering -> True; a fresh install where nothing answered yet -> False (Settings says "No brain yet")."""
    return bool(store.get_setting("model.chat") or store.get_setting(FALLBACK_SETTING))


# ── The fallback model: what Odie uses when nothing is chosen in Settings ──
FALLBACK_SETTING = "model.fallback"  # {"provider": ..., "model": ...}, written by refresh_fallback()


def pick_fallback(local_listing: list[dict], presets_with_keys: list[Preset], configured_model: str) -> dict | None:
    """Which model to use when none is chosen: the first provider that can actually answer, in this order:
      1. LM Studio, if it answers GET /models with a chat model
      2. Ollama, the same
      3. each cloud preset that has a key, in PRESETS order (OpenAI, OpenRouter, Gemini, Claude)
    A local provider gets the configured model (ODIE_MODEL) when it lists it, else the first model it lists; a cloud
    preset gets its default_model.
      local_listing      list_models() for LM Studio and Ollama: an entry whose error is None answered
      presets_with_keys  keyed_presets()
    Worked example: nothing chosen, LM Studio off (error "ConnectError"), Ollama answers with glm-5.3-flash:cloud
      -> {"provider": "ollama", "model": "glm-5.3-flash:cloud"}
    Another: both local ones off, keys for OpenAI and Claude -> {"provider": "openai", "model": "gpt-5.5"}.
    None when nothing answers and no key is set (resolve_selection then keeps LM Studio + the configured model)."""
    for entry in local_listing:
        answered = entry["error"] is None
        listed = [m["id"] for m in entry["models"]]
        if not answered or not listed:
            continue
        if configured_model in listed:
            return {"provider": entry["id"], "model": configured_model}
        return {"provider": entry["id"], "model": listed[0]}
    if presets_with_keys:
        first = presets_with_keys[0]
        return {"provider": first.id, "model": first.default_model}
    return None


async def ask_local_providers(transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """LM Studio's and Ollama's model lists (a quick GET /models on this computer, or wherever their .env address
    points). Tests replace this: they never reach the real ones."""
    return await list_models(local_providers(), transport=transport)


async def refresh_fallback(store: Store, transport: httpx.AsyncBaseTransport | None = None) -> dict | None:
    """Work out the fallback model now and save it for resolve_selection. Run at startup and whenever providers change
    (a key added or removed, a custom provider added or removed)."""
    local_listing = await ask_local_providers(transport)
    picked = pick_fallback(local_listing, keyed_presets(), config.settings.model_id)
    previous = store.get_setting(FALLBACK_SETTING)
    if picked == previous:
        return picked
    store.set_setting(FALLBACK_SETTING, picked)
    if picked:
        log.info("Fallback model (used while nothing is chosen in Settings): %s / %s", picked["provider"], picked["model"])
    else:
        log.info("No provider answered and no cloud key is set: the fallback stays LM Studio / %s", config.settings.model_id)
    return picked


STARTUP_RECHECKS = (30, 60, 120)  # seconds: LM Studio often starts at login alongside Odie, a little after it


async def refresh_fallback_at_startup(store: Store, waits: tuple[int, ...] = STARTUP_RECHECKS) -> None:
    """refresh_fallback() now, and again a few times while LM Studio (the first choice) hasn't answered yet, so a slow
    start at login doesn't leave Odie on a later choice until the next restart."""
    picked = await refresh_fallback(store)
    for wait in waits:
        if picked and picked["provider"] == "lmstudio":
            return
        await asyncio.sleep(wait)
        picked = await refresh_fallback(store)


async def chat_completion(store: Store, slot: str, messages: list[dict], thinking: bool = False, **opts) -> str:
    """One plain completion on the slot's model (used by the brief, memory review and day summary), through the same
    litellm call the agent uses (odie.agent.model.complete). opts: temperature, max_tokens; litellm drops what the model
    refuses (Claude takes no temperature while it thinks)."""
    from odie.agent.model import complete
    sel = resolve_selection(store, slot)
    reply = await complete(sel, messages, think_harder=thinking, **opts)
    choice = reply.choices[0]
    text = (choice.message.content or "").strip()
    if not text:  # a thinking model can spend the whole budget reasoning; say so instead of failing quietly
        log.error("%s model %s returned no text (finish_reason=%s)", slot, sel.model, choice.finish_reason)
    return text


HISTORY_LIMIT_SHARE = 0.75      # 3/4 of the model's window: room for the system prompt, tools and the reply
HISTORY_LIMIT_CAP = 300_000      # a 1M window would make every turn slow and costly long before it filled
HISTORY_LIMIT_UNKNOWN = 50_000   # a provider that can't say


def history_limit_for(window: int | None) -> int:
    """Tokens a chat's history may reach before its older turns go as words only (odie.agent.compaction).
      DeepSeek or Claude, 1M window -> 300,000 (the cap); GLM, 198k -> 148,500; Gemma at 70k -> 52,500;
      a provider that can't say -> 50,000"""
    if not window:
        return HISTORY_LIMIT_UNKNOWN
    return min(HISTORY_LIMIT_CAP, int(window * HISTORY_LIMIT_SHARE))


async def context_window(sel: Selection, transport: httpx.AsyncBaseTransport | None = None) -> int | None:
    """The model's context size as its provider reports it: LM Studio's loaded size (else its maximum), or
    Ollama's model info. None when the provider doesn't say or can't be reached."""
    root = sel.provider.base_url.removesuffix("/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5, transport=transport) as c:
            if sel.provider.id == "lmstudio":
                r = await c.get(f"{root}/api/v0/models/{sel.model}")
                r.raise_for_status()
                d = r.json()
                return int(d.get("loaded_context_length") or d.get("max_context_length") or 0) or None
            if sel.provider.id == "ollama":
                r = await c.post(f"{root}/api/show", json={"model": sel.model})
                r.raise_for_status()
                info = r.json().get("model_info") or {}
                return next((int(v) for k, v in info.items() if k.endswith(".context_length") and v), None)
            if sel.provider.id == "openrouter":
                m = next((m for m in await _models_of(c, sel.provider) if m.get("id") == sel.model), None)
                return int(m["context_length"]) if m and m.get("context_length") else PRESET_BY_ID["openrouter"].window
    except (httpx.HTTPError, ValueError, TypeError):
        return PRESET_BY_ID[sel.provider.id].window if sel.provider.id in PRESET_BY_ID else None
    return PRESET_BY_ID[sel.provider.id].window if sel.provider.id in PRESET_BY_ID else None
