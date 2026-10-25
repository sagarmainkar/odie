"""The setup-only tools: everything the setup conversation can do, and nothing else (no shell, web or memory). Each
returns {"result": ...}, {"error": "<plain reason>"} (its step's failure count goes up), and maybe a "card" for the
screen. Keys are never taken here: request_key only asks the screen to show a key form."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import httpx

from odie import config, persona, profile
from odie.secrets import load_secret
from odie.setup import state


def setup_home() -> Path:
    """Where Obsidian's own vault list is read and a new vault is made (tests point it elsewhere)."""
    return Path(os.environ.get("ODIE_SETUP_HOME") or Path.home()).expanduser()


def _fn(name: str, description: str, props: dict | None = None, required: tuple = ()) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": props or {}, "required": list(required)}}}


DECLARATIONS = [
    _fn("set_names", "Save what to call the user, and the assistant's name (Odie if they're happy with it).",
        {"user_name": {"type": "string"}, "assistant_name": {"type": "string"}}, ("user_name",)),
    _fn("vault_options", "The Obsidian vaults on this computer, and where a new one would go."),
    _fn("set_vault", "Use a vault: existing (one Obsidian knows), elsewhere (any folder, a full path), new (create one), or skip.",
        {"choice": {"type": "string", "enum": ["existing", "elsewhere", "new", "skip"]}, "path": {"type": "string"}}, ("choice",)),
    _fn("embedding_options", "The ways to read the vault by meaning: local embedding models found here, or OpenAI."),
    _fn("set_embeddings", "Read the vault by meaning with this embedding model (it is checked first).",
        {"provider": {"type": "string", "enum": ["openai", "lmstudio", "ollama"]}, "model": {"type": "string"}}, ("provider", "model")),
    _fn("set_photos", "Read the user's Photos library, read-only and on this Mac, so pictures can be searched by who, where and "
        "when (on: true); or not (on: false).", {"on": {"type": "boolean"}}, ("on",)),
    _fn("search_status", "Which web search is in use, and the keys that would make it better."),
    _fn("voice_options", "The voices for reading replies aloud."),
    _fn("set_voice", "Read replies aloud with this voice engine.", {"engine": {"type": "string", "enum": ["kokoro", "openai"]}}, ("engine",)),
    _fn("apps_options", "How to connect apps such as Gmail and Calendar (Zapier or Composio)."),
    _fn("connect_app", "Show the user the form for their Zapier or Composio link. You never see the link; you're told when it is saved.",
        {"app": {"type": "string", "enum": ["zapier", "composio"]}}, ("app",)),
    _fn("phone_status", "How to open the assistant on the user's phone."),
    _fn("request_key", "Show the user a key form for a provider. You never see the key; you're told when it is saved.",
        {"provider": {"type": "string", "enum": ["openai", "openrouter", "gemini", "anthropic", "tavily", "brave", "ollama"]}}, ("provider",)),
    _fn("skip_step", "The user wants to skip this step for now.",
        {"step": {"type": "string", "enum": sorted(state.SKIPPABLE)}}, ("step",)),
    _fn("finish_setup", "Only when every step is done or skipped (setup finishes by itself then): finish setup."),
]

STEP_OF = {"set_names": "names", "vault_options": "vault", "set_vault": "vault", "embedding_options": "embeddings",
           "set_embeddings": "embeddings", "set_photos": "photos", "search_status": "search", "voice_options": "voice", "set_voice": "voice",
           "apps_options": "apps", "connect_app": "apps", "phone_status": "phone"}


class _Error(Exception):
    """A plain reason, given back to the model."""


# ── the tools ──
async def set_names(store, user_name: str, assistant_name: str | None = None) -> dict:
    if not (user_name or "").strip():
        raise _Error("The user's name is empty: ask what to call them.")
    profile.set_user_name(store, user_name)
    if assistant_name and assistant_name.strip():
        persona.set_name(store, assistant_name)
    state.mark(store, "names", "done")
    return {"user_name": profile.get(store)["user_name"], "assistant_name": persona.get(store)["name"]}


def _obsidian_vaults() -> list[dict]:
    home = setup_home()
    for cfg in (home / "Library" / "Application Support" / "obsidian" / "obsidian.json", home / ".config" / "obsidian" / "obsidian.json"):
        try:
            vaults = json.loads(cfg.read_text()).get("vaults") or {}
        except (OSError, ValueError):
            continue
        out = []
        for v in vaults.values():
            p = Path(str(v.get("path") or ""))
            if p.is_absolute() and p.is_dir():
                out.append({"name": p.name, "path": str(p)})
        return out
    return []


def _folder(name: str) -> str:
    """The assistant's name as a safe folder name: no separators, no leading dots."""
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip().lstrip(". ")
    return safe or "Odie"


def _new_path(store) -> Path:
    home, name = setup_home(), _folder(persona.get(store)["name"])
    return home / "Documents" / f"{name} Vault" if (home / "Documents").is_dir() else home / f"{name.lower()}-vault"


async def vault_options(store) -> dict:
    return {"known": _obsidian_vaults(), "new_path": str(_new_path(store)), "elsewhere": "any folder, given as a full path"}


async def set_vault(store, choice: str, path: str | None = None, runner=None) -> dict:
    from odie.vault import settings
    if choice == "skip":
        state.mark(store, "vault", "skipped")
        state.mark(store, "embeddings", "skipped")  # nothing to read by meaning
        return {"vault": None}
    if choice == "new":
        target = Path(path).expanduser() if path else _new_path(store)
        if not target.is_absolute():
            raise _Error(f"A new vault needs a full path (like {_new_path(store)}), not {path!r}.")
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise _Error(f"There's already something at {target}: pick another name, or use it as an existing vault.")
        name = _folder(persona.get(store)["name"])
        if not (target / name).resolve().is_relative_to(target.resolve()):
            raise _Error("That name can't be a folder inside the vault.")
        (target / name).mkdir(parents=True, exist_ok=True)
        (target / "Welcome.md").write_text(f"# Welcome\n\nThis is {name}'s vault: your notes live here, and {name} can search them.\n")
        (target / name / "Memories.md").write_text("# Memories\n")
        path = str(target)
    elif choice not in ("existing", "elsewhere"):
        raise _Error("choice is existing, elsewhere, new or skip.")
    try:
        settings.put(store, dir=path or "")
    except ValueError as e:
        raise _Error(str(e)) from None
    if not settings.get(store)["dir"]:
        raise _Error("Which folder? Give its full path.")
    state.mark(store, "vault", "done")
    await _apply_vault(runner)
    return {"vault": settings.get(store)["dir"], "created": choice == "new"}


async def _apply_vault(runner, photos: bool = False) -> None:
    """What setup saved for the vault (or the photos) is live at once: the search tools reloaded, indexing started."""
    if runner is None:
        return
    reload = getattr(runner, "reload_vault", None)
    if reload is not None:
        await reload()
    worker = getattr(runner, "vault_worker", None)
    if worker is not None:
        if photos:
            worker.kick(photos=True)
        else:
            worker.kick()


async def embedding_options(store, transport=None) -> dict:
    from odie import embed_worker, machine
    options = []
    # Odie's own service: when its environment is there (uv sync in embed_server) and this Mac is meant to run it
    # (not an Intel Mac: PyTorch has no build there, and the installer set ODIE_EMBED=off)
    if embed_worker.EmbedWorker().installed and machine.local_embeddings_wanted():
        options.append({"provider": "gemma", "model": embed_worker.MODEL, "local": True,
                        "note": "on this Mac: Odie's own embedding service (EmbeddingGemma 2); nothing leaves the computer"})
    async with httpx.AsyncClient(timeout=4, transport=transport) as c:
        try:
            r = await c.get(config.settings.lm_studio_base_url.rstrip("/") + "/models")
            options += [{"provider": "lmstudio", "model": m["id"], "local": True, "note": "on this computer (LM Studio)"}
                        for m in r.json().get("data", []) if "embed" in m.get("id", "").lower()]
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        try:
            r = await c.get("http://localhost:11434/api/tags")
            names = [m["name"] for m in r.json().get("models", []) if "embed" in m.get("name", "").lower()]
        except (httpx.HTTPError, ValueError, AttributeError):
            names = []
    from odie.vault.embed import ollama_sees_pictures
    for name in names:
        sees = await ollama_sees_pictures(name, transport)
        note = "on this computer (Ollama); reads pictures too" if sees else "on this computer (Ollama)"
        options.append({"provider": "ollama", "model": name, "local": True, "note": note})
    options.append({"provider": "openai", "model": "text-embedding-3-small", "local": False,
                    "needs_key": not load_secret("OPENAI_API_KEY"),
                    "note": "OpenAI: note text is sent to OpenAI to be read; it usually costs a few cents"})
    return {"options": options}


async def set_embeddings(store, provider: str, model: str, runner=None, transport=None) -> dict:
    from odie.vault import embed, settings
    if not settings.configured(store):
        raise _Error("There's no vault to read yet: set up the vault first, or skip this step.")
    try:
        dims = await embed.check(embed.make_embedder(provider, model, store, transport))
    except embed.EmbedError as e:
        raise _Error(str(e)) from None
    # the model reads pictures by their look: Odie's own service always; on Ollama, one that lists "vision"
    pictures = provider == "gemma" or (provider == "ollama" and await embed.ollama_sees_pictures(model, transport))
    settings.put(store, embeddings={"provider": provider, "model": model, "pictures": pictures})
    state.mark(store, "embeddings", "done")
    await _apply_vault(runner)
    note = ("The model is downloading in the background (about 1.5 GB, a few minutes); reading the notes starts by itself "
            "when it's here." if dims == 0 else "Indexing runs in the background; a big vault takes a while.")
    return {"embeddings": f"{provider}:{model}", "note": note}


async def set_photos(store, on: bool, runner=None) -> dict:
    from odie.photos import settings
    settings.put(store, on=bool(on))
    state.mark(store, "photos", "done" if on else "skipped")
    await _apply_vault(runner, photos=True)
    return {"photos": "on" if on else "off", "note": "The library is read in the background; it takes a few seconds."}


async def search_status(store) -> dict:
    from odie.agent.tools.web import PROVIDERS, configured_keys
    have = {pid for pid, _ in configured_keys()}
    using = [p.name for p in PROVIDERS if p.id in have]
    return {"using": using or ["the free fallback (it works, with plainer results)"],
            "offer": [{"provider": p.id, "name": p.name} for p in PROVIDERS if p.id not in have]}


async def voice_options(store) -> dict:
    from odie import machine
    has_openai = bool(load_secret("OPENAI_API_KEY"))
    options = []
    if machine.local_voice_wanted():  # Kokoro needs Apple Silicon: an Intel Mac gets OpenAI's voices only
        options.append({"engine": "kokoro", "label": "Free local voice", "note": "private, runs on this computer"})
    options.append({"engine": "openai", "label": "OpenAI voice", "note": "natural; the text goes to OpenAI", "needs_key": not has_openai})
    return {"options": options, "or": "skip: the app can still read replies with the browser's own voice"}


async def set_voice(store, engine: str) -> dict:
    from odie import voice
    if engine == "openai" and not load_secret("OPENAI_API_KEY"):
        raise _Error("The OpenAI voice needs an OpenAI key: call request_key('openai') first.")
    if engine not in ("kokoro", "openai"):
        raise _Error("engine is kokoro or openai (or skip the step).")
    from odie import machine
    if engine == "kokoro" and not machine.local_voice_wanted():
        raise _Error("Odie's own voice doesn't run on this Mac (it needs Apple Silicon): choose openai, or skip the step.")
    voice.set_tts(store, engine=engine)
    state.mark(store, "voice", "done")
    return {"voice": engine}


async def apps_options(store) -> dict:
    return {"say": ("Gmail, Calendar and many more connect through Zapier (mcp.zapier.com) or Composio "
                    "(dashboard.composio.dev). Your data then goes through that service. If they have an account, call "
                    "connect_app and they paste its link into the form; most people skip this for now."),
            "apps": ["zapier", "composio"], "settings": "#settings"}


async def connect_app(store, app: str) -> dict:
    from odie.plugins.presets import PRESETS
    p = PRESETS.get(app)
    if p is None:
        raise _Error(f"There's no form for {app!r}: Zapier or Composio.")
    return {"result": "The form is on the screen. Wait until the user saves it; you'll be told. You never see the link.",
            "card": {"type": "app", "app": app, "label": p["title"], "where": p["where"], "key_label": p["key_label"]}}


async def phone_status(store) -> dict:
    return {"address": config.settings.public_url, "tailscale_installed": shutil.which("tailscale") is not None,
            "say": ("Open this address on your phone's browser, then Add to Home Screen. Outside your home network, Tailscale "
                    "gives the phone a private way in.")}


KEYS = {"openai": ("provider", "OpenAI", "Chats, notes and memory you send to it go to OpenAI."),
        "openrouter": ("provider", "OpenRouter", "Chats, notes and memory go to OpenRouter and the model's company."),
        "gemini": ("provider", "Gemini", "Chats, notes and memory go to Google."),
        "anthropic": ("provider", "Claude", "Chats, notes and memory go to Anthropic."),
        "tavily": ("search", "Tavily", "Your web searches go to Tavily."),
        "brave": ("search", "Brave Search", "Your web searches go to Brave."),
        "ollama": ("search", "Ollama web search", "Your web searches go to Ollama.")}


async def request_key(store, provider: str) -> dict:
    if provider not in KEYS:
        raise _Error(f"There's no key form for {provider!r}.")
    kind, label, note = KEYS[provider]
    return {"result": "The key form is on the screen. Wait until the user saves it; you'll be told.",
            "card": {"type": "key", "provider": provider, "kind": kind, "label": label, "note": note}}


async def skip_step(store, step: str) -> dict:
    if step not in state.SKIPPABLE:
        raise _Error("Only the vault, embeddings, search, voice, apps and phone steps can be skipped.")
    state.mark(store, step, "skipped")
    return {"skipped": step}


async def finish_setup(store) -> dict:
    s = state.get(store)
    if s["steps"]["names"] == "todo":
        raise _Error("Ask what to call the user first: their name can't be skipped.")
    left = [k for k, v in s["steps"].items() if v == "todo"]
    if left:
        raise _Error(f"These steps aren't done yet: {', '.join(left)}. Ask about them, or skip_step each one the user wants to skip.")
    state.finish(store)
    return {"done": True}


TOOLS = {f.__name__: f for f in (set_names, vault_options, set_vault, embedding_options, set_embeddings, set_photos, search_status,
                                  voice_options, set_voice, apps_options, connect_app, phone_status, request_key, skip_step,
                                  finish_setup)}


async def run(name: str, args: dict, store, runner=None, transport=None) -> dict:
    """Run one setup tool by name. A failure is a plain reason, counted against its step."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"There's no tool called {name}."}
    kwargs = {k: v for k, v in dict(args or {}).items() if k not in ("runner", "transport")}
    if name in ("embedding_options", "set_embeddings"):
        kwargs["transport"] = transport
    if name in ("set_vault", "set_embeddings", "set_photos"):
        kwargs["runner"] = runner
    try:
        out = await fn(store, **kwargs)
    except Exception as e:  # noqa: BLE001  (any failure is a plain reason for the model, never a broken turn)
        if name in STEP_OF:
            state.note_failure(store, STEP_OF[name])
        if isinstance(e, _Error):
            return {"error": str(e)}
        if isinstance(e, TypeError):
            return {"error": f"Wrong arguments for {name}."}
        return {"error": f"{name} failed: {e}" if str(e) else f"{name} failed ({type(e).__name__})."}
    if isinstance(out, dict) and "card" in out:
        return out
    return {"result": out}
