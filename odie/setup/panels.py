"""Setup's steps as the screen shows them: each step's question, a line on what it is, its choices (and what a choice
needs first: a key form, an app form, a folder), and Skip. A choice made on the screen is applied here, by code: the
model never decides what is saved, so the checklist only says what really is."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from odie import config, persona, profile
from odie.secrets import load_secret
from odie.setup import state, tools

TAILSCALE_DOWNLOAD = "https://tailscale.com/download"

QUESTIONS = {
    "names": "First, what should I call you? I'm {name}: keep that name, or give me another.",
    "vault": "Where should your notes live? I keep your notes and my memory in an Obsidian vault: a folder of Markdown notes.",
    "embeddings": "Should I search your notes by meaning, not just by their words?",
    "photos": "May I look at your Photos library?",
    "search": "Which web search should I use?",
    "voice": "How should I read replies aloud?",
    "apps": "Should I reach your apps, like Gmail and Calendar?",
    "phone": "Last one: do you want to use me on your phone?",
}
EXPLAIN = {
    "vault": "Pick one Obsidian already knows, make a new one, or point at any folder.",
    "embeddings": ("That needs an embedding model: a small model that turns each note into numbers so similar ideas sit "
                   "together. It's separate from the chat model you picked. Without one I still find notes by their words."),
    "photos": ("I read what Photos already knows about each picture and video: the people in it, what it shows, where and "
               "when it was taken, its albums. Then you can ask me for pictures by who, where or when. Nothing leaves this "
               "Mac and nothing is changed; hidden photos are never read."),
    "search": "With a key, results are better. Without one I use a free search that works, with plainer results.",
    "voice": "You can change this any time in Settings.",
    "apps": "That goes through Zapier or Composio: you pick the apps there, and your data then goes through that service.",
    "phone": ("Your phone reaches this computer through Tailscale: a private network between your own devices, like a VPN "
              "that only you are on. It is free for personal use and safe: nothing is opened to the internet, and it works "
              "anywhere, not just at home."),
}
SKIP = {
    "vault": "Skip: no notes for now", "embeddings": "Skip: find notes by their words", "photos": "Skip: no photos for now",
    "search": "Skip: use the free search",
    "voice": "Skip: use the browser's own voice", "apps": "Skip: no apps for now", "phone": "Skip: no phone for now",
}
LABEL = {"names": "Names", "vault": "Notes", "embeddings": "Search by meaning", "photos": "Photos", "search": "Web search",
         "voice": "Voice", "apps": "Apps", "phone": "Phone"}

ZAPIER_STEPS = [
    "On mcp.zapier.com, make a new MCP server and choose “Other” as the client.",
    "Add the tools you want, for example Gmail (and Calendar), and connect your Google account when Zapier asks.",
    "Open Connect: Zapier shows a server link and a code. Copy both into the two boxes below.",
]
COMPOSIO_STEPS = [
    "On dashboard.composio.dev, open MCP and make a server with the apps you want (Gmail, Calendar…).",
    "Copy its server link, and its API key if it shows one, into the boxes below.",
]


class ChoiceError(Exception):
    """A plain reason the choice didn't work; nothing was saved."""


def tailscale_installed() -> bool:
    return shutil.which("tailscale") is not None or Path("/Applications/Tailscale.app").exists()


def serve_address_now() -> str:
    """Asks Tailscale whether it already passes Odie's port to the phone, the way `odie restart` does at start, so
    Check again finds a `tailscale serve` run after Odie started, with no restart. Serving -> "https://mac.ts.net";
    not serving, or no tailscale command -> ""."""
    from odie import cli
    return cli.tailscale_phone_address(config.settings.port, cli.Runner())


def _key_card(provider: str) -> dict:
    kind, label, note = tools.KEYS[provider]
    return {"type": "key", "provider": provider, "kind": kind, "label": label, "note": note}


def _app_card(app: str) -> dict:
    from odie.plugins.presets import PRESETS
    p = PRESETS[app]
    if app == "zapier":
        return {"type": "app", "app": app, "label": p["title"], "where": p["where"], "steps": ZAPIER_STEPS,
                "key_label": "Zapier's code (if any)"}
    return {"type": "app", "app": app, "label": p["title"], "where": p["where"], "steps": COMPOSIO_STEPS, "key_label": p["key_label"]}


def _choice(cid: str, label: str, note: str = "", recommended: bool = False, needs: dict | None = None, value=None) -> dict:
    return {"id": cid, "label": label, "note": note, "recommended": recommended, "needs": needs, "value": value}


async def panel(store, step: str | None = None, transport=None) -> dict | None:
    """The step's question and controls (the current step if none is named), or None when setup is done."""
    s = state.get(store)
    step = step or state.current(s)
    if step is None or step == "brain":
        return None
    name = persona.get(store)["name"]
    out = {"step": step, "label": LABEL[step], "question": QUESTIONS[step].format(name=name), "explain": EXPLAIN.get(step, ""),
           "choices": [], "skip": SKIP.get(step), "fields": [], "phone": None}
    if step == "names":
        out["fields"] = [{"id": "user_name", "label": "Your name", "value": profile.get(store)["user_name"] or ""},
                         {"id": "assistant_name", "label": "Your assistant's name", "value": name}]
        out["choices"] = [_choice("save", "Continue")]
    elif step == "vault":
        opts = await tools.vault_options(store)
        out["choices"] = [_choice("existing", v["name"], v["path"], value=v["path"]) for v in opts["known"]]
        out["choices"] += [_choice("new", "Make a new vault", opts["new_path"]),
                           _choice("elsewhere", "Another folder", "Type its full path", needs={"type": "path"})]
    elif step == "embeddings":
        opts = (await tools.embedding_options(store, transport=transport))["options"]
        for i, o in enumerate(opts):
            needs = _key_card("openai") if o.get("needs_key") else None
            out["choices"].append(_choice(f"{o['provider']}:{o['model']}", o["model"], o["note"], needs=needs))
    elif step == "photos":
        out["choices"] = [_choice("yes", "Yes, read my photos and videos", "A few seconds, in the background; read-only")]
    elif step == "search":
        from odie.agent.tools.web import PROVIDERS, configured_keys
        have = {pid for pid, _ in configured_keys()}
        out["choices"] = [_choice(p.id, p.name + (" (key saved)" if p.id in have else ""), tools.KEYS[p.id][2],
                                  needs=None if p.id in have else _key_card(p.id)) for p in PROVIDERS]
    elif step == "voice":
        from odie import machine
        has_openai = bool(load_secret("OPENAI_API_KEY"))
        out["choices"] = []
        if machine.local_voice_wanted():  # Kokoro needs Apple Silicon: an Intel Mac is offered OpenAI's voices only
            out["choices"].append(_choice("kokoro", "Kokoro", "Free, private: runs on this computer"))
        out["choices"].append(_choice("openai", "OpenAI voice", "Natural; the text goes to OpenAI",
                                      needs=None if has_openai else _key_card("openai")))
    elif step == "apps":
        out["choices"] = [_choice("zapier", "Zapier", "mcp.zapier.com", needs=_app_card("zapier")),
                          _choice("composio", "Composio", "dashboard.composio.dev", needs=_app_card("composio"))]
        from odie.mac import permissions, scripts
        if scripts.available():  # the Mac's own apps first: no account, just macOS's permission for each
            out["mac_apps"] = {"mac": True, "apps": [r.as_dict() for r in permissions.rows()], "default_calendar": ""}
    elif step == "phone":
        from odie import devices
        installed = tailscale_installed()
        address = config.phone_address()
        if installed and not address:  # Check again after `tailscale serve`: look now, don't wait for a restart
            found = await asyncio.to_thread(serve_address_now)
            if found:
                config.learn_public_url(found)
                address = config.phone_address()
        out["phone"] = {
            "tailscale": installed, "serving": bool(address), "address": address, "pairing": devices.pairing_on(store),
            "download": TAILSCALE_DOWNLOAD, "serve_command": f"tailscale serve --bg {config.settings.port}",
            "steps": ["Install Tailscale on your phone and sign in with the same account as this computer.",
                      "Scan the code below with the phone's camera (or open the address and type the code)."
                      if devices.pairing_on(store) else "Open the address above in the phone's browser.",
                      "In the phone's browser, choose Add to Home Screen: I open like an app from then on."],
        }
        if installed and address:
            # Pairing the phone can wait: "later" finishes the step with the address kept; Settings → Phone has the code.
            out["choices"] = [_choice("paired", "My phone is paired" if devices.pairing_on(store) else "My phone opens it"),
                              _choice("later", "Later, from Settings → Phone", "The address stays; pair whenever the phone is at hand")]
        elif not installed:  # "note": for setup's chat model only; the phone card shows the same as steps
            out["note"] = f"Tailscale isn't on this computer yet: get it at {TAILSCALE_DOWNLOAD}, sign in, then Check again."
        else:
            out["note"] = ("Tailscale is here, but it doesn't pass your phone to me yet: run "
                           f"`tailscale serve --bg {config.settings.port}` in Terminal, then Check again. If it still "
                           "doesn't show, run `odie restart` in Terminal, refresh this page, and Check again.")
    return out


def _check_choice(p: dict, choice: str) -> dict:
    found = next((c for c in p["choices"] if c["id"] == choice), None)
    if found is None:
        raise ValueError(f"{choice!r} isn't a choice for {p['step']}")
    return found


async def apply(store, step: str, choice: str, value=None, runner=None, transport=None) -> str:
    """Saves what was chosen on the screen and returns the line that says so. ValueError: not a choice of that step.
    ChoiceError: the choice didn't work (a plain reason; nothing saved)."""
    if step not in state.STEPS or step == "brain":
        raise ValueError("not a setup step")
    if choice == "skip":
        if step not in state.SKIPPABLE:
            raise ValueError("that step can't be skipped")
        if state.get(store)["steps"][step] == "done":
            raise ValueError("that step is already done")
        state.mark(store, step, "skipped")
        if step == "vault":
            state.mark(store, "embeddings", "skipped")  # nothing to search by meaning
        return f"Skipped {LABEL[step].lower()} for now: it's in Settings when you want it."
    p = await panel(store, step, transport=transport)
    found = _check_choice(p, choice)

    async def run(name: str, **args):
        out = await tools.run(name, args, store, runner=runner, transport=transport)
        if "error" in out:
            raise ChoiceError(out["error"])
        return out["result"]

    if step == "names":
        v = value if isinstance(value, dict) else {}
        got = await run("set_names", user_name=str(v.get("user_name") or ""), assistant_name=str(v.get("assistant_name") or ""))
        return f"Hi {got['user_name']}! I'm {got['assistant_name']}."
    if step == "vault":
        path = found.get("value") if choice == "existing" else (str(value or "") if choice == "elsewhere" else None)
        got = await run("set_vault", choice=choice, path=path)
        return f"I made a new vault at {got['vault']}." if got.get("created") else f"Your notes: {got['vault']}."
    if step == "embeddings":
        provider, _, model = choice.partition(":")
        await run("set_embeddings", provider=provider, model=model)
        return f"I'll search your notes by meaning with {model}. Reading them runs in the background."
    if step == "photos":
        await run("set_photos", on=True)
        return "I'll read your photo library in the background. Ask me for pictures by who, where or when."
    if step == "search":
        from odie.agent.tools.web import PROVIDERS, configured_keys
        if choice not in {pid for pid, _ in configured_keys()}:
            raise ChoiceError(f"Save the {tools.KEYS[choice][1]} key in the form first.")
        state.mark(store, "search", "done")
        return f"Web search: {next(x.name for x in PROVIDERS if x.id == choice)}."
    if step == "voice":
        await run("set_voice", engine=choice)
        return f"Voice: {found['label']}."
    if step == "apps":
        from odie.plugins.mcp import read_config
        from odie.plugins.presets import preset_of
        servers, _ = read_config()
        if not any(isinstance(sp, dict) and preset_of(str(sp.get("url") or "")) == choice for sp in servers.values()):
            raise ChoiceError(f"{found['label']} isn't connected yet: fill in the form and press Check and connect.")
        state.mark(store, "apps", "done")
        return f"Apps: {found['label']} is connected."
    if step == "phone":
        from odie import devices
        if choice == "later":
            state.mark(store, "phone", "done")
            return "Whenever the phone is at hand: Settings → Phone has the address and the pairing code."
        if devices.pairing_on(store) and len(devices.list_devices(store)) < 2:
            raise ChoiceError("No phone has paired yet: scan the code with the phone's camera first, then press this again.")
        state.mark(store, "phone", "done")
        return "Your phone is set up."
    raise ValueError("not a setup step")


def summary(store) -> str:
    """What setup really saved, from the settings themselves."""
    from odie import voice
    from odie.agent.tools.web import PROVIDERS, configured_keys
    from odie.vault import settings as vault
    s = state.get(store)["steps"]
    v = vault.get(store)
    have = {pid for pid, _ in configured_keys()}
    search = ", ".join(p.name for p in PROVIDERS if p.id in have) or "the free one"
    emb = v.get("embeddings") or {}
    from odie.plugins.mcp import read_config
    apps = ", ".join(str(sp.get("title") or k) for k, sp in read_config()[0].items() if isinstance(sp, dict)) if s["apps"] == "done" else ""

    def line(step: str, text: str) -> str:
        return f"- {LABEL[step]}: {text if s[step] == 'done' else 'skipped'}"
    return "\n".join([
        "That's everything. Here's what's set:",
        f"- You: {profile.get(store)['user_name']} · me: {persona.get(store)['name']}",
        line("vault", v.get("dir") or ""),
        line("embeddings", f"{emb.get('model', '')} ({emb.get('provider', '')})"),
        line("photos", "on"),
        f"- {LABEL['search']}: {search}",
        line("voice", voice.get_tts(store)[0].capitalize()),
        line("apps", apps),
        line("phone", "paired"),
        "Anything skipped is in Settings whenever you want it.",
    ])
