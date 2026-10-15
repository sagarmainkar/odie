"""What Odie can do right now, read from its live state (tools, skills, apps, models, voice, trackers, schedule,
blocks), so "what can you do?" gets a true answer instead of a guess. Used by the about-odie skill."""
from __future__ import annotations

hooks: dict = {"runner": None}  # set by the runner

# Built-in abilities: shown when any of their tools is present.
ABILITIES = [
    ("Tasks and reminders", ("task_add", "task_list"), "to-dos with due times; due reminders ping the phone"),
    ("Memory", ("fetch_memory", "update_memory"), "long-term memory kept in Obsidian, reviewed every few turns"),
    ("Notes and photos", ("search_everything", "read_note"), "search the user's notes (by words, and meaning when set up) and their photos and videos (by who, where, when and what is in them) in one go; read a note, find related ones; read-only"),
    ("Notes", ("search_notes", "read_note"), "search the user's notes by words (and meaning, when set up), read one, find related ones; read-only"),
    ("Web", ("web_search", "web_fetch"), "search the web and read pages, with sources"),
    ("Commands on this computer", ("run_shell",), "run commands on this computer; each one asks for the user's tap"),
]

# What runs on its own (scheduler job id -> what it does). A test keeps this in step with the scheduler.
SCHEDULE = {
    "brief": "Morning brief at 07:30: a short push and a message in Chat",
    "reminders": "Reminders checked every minute",
    "expiry": "Approvals left untapped lapse after 24 hours",
    "news": "News on Today refreshed at 06, 10, 14, 18 and 22",
    "background": "The background agent every 5 minutes (and once just after start): the mail and calendar watch every 30 minutes, then trackers that are due, one at a time",
}

EXTEND = [
    "New skill: ask Odie to build one (\"build me a skill for ...\"); it drafts it and installs it after the user approves",
    "Skill folders dropped in ~/.odie/skills; skills with code need Allow code in Settings",
    "Connected apps (MCP servers): Settings > Connected apps > Connect another app",
    "Model providers (OpenAI, OpenRouter, Gemini, Claude, any OpenAI-compatible): Settings > Providers; models in Brain",
    "Trackers: \"track ... and tell me when ...\"",
]


def abilities() -> list[tuple[str, tuple[str, ...], str]]:
    from odie import addons
    return ABILITIES + [x for a in addons.active() for x in a.abilities]


def schedule() -> dict[str, str]:
    """What runs on its own: the core jobs, then each add-on job (one whose id is taken isn't scheduled, so isn't here)."""
    from odie import addons
    out = dict(SCHEDULE)
    for a in addons.active():
        for j in a.jobs:
            out.setdefault(j.id, j.about)
    return out


def _section(title: str, lines: list[str]) -> str:
    return f"## {title}\n" + ("\n".join(f"- {x}" for x in lines) if lines else "- none")


def phone_lines(store) -> list[str]:
    """How a phone reaches Odie and pairs: the facts, so the answer is never made up."""
    from odie import config, devices
    address = config.phone_address()
    lines = [f"Phone address: {address}" if address else
             "There's no phone address yet: the phone reaches this computer through Tailscale (tailscale.com/download), "
             f"then `tailscale serve --bg {config.settings.port}` on this computer and a restart of Odie"]
    lines.append("The phone needs Tailscale too, signed in to the same account")
    if devices.pairing_on(store):
        lines += [f"Paired devices: {len(devices.list_devices(store))}",
                  "To pair a phone: on a device that's already paired (this computer), open Settings > Devices > Add a "
                  "device. It shows a QR code and an 8-letter code, valid once for 10 minutes. Scan the QR code with the "
                  "phone's camera, or open the phone address and type the code. The grey ABCD-EFGH in the code box is only "
                  "an example",
                  "No paired device at hand: the recovery passcode (four words) pairs one instead"]
    else:
        lines.append("Pairing is off: any device that can reach the address can use Odie (Settings > Devices turns it on)")
    lines.append("Then, in the phone's browser: Add to Home Screen, so Odie opens like an app")
    return lines


def features() -> str:
    from odie import trackers, voice
    from odie.blocks import kinds
    from odie.models import all_providers, resolve_selection
    r = hooks["runner"]
    store = r.store
    names = set(r._all_tool_names())
    out = ["What Odie has right now (live). Answer from this; don't promise anything not listed."]
    out.append(_section("Built in", [f"{label}: {text}" for label, tools, text in abilities() if any(t in names for t in tools)]))
    skills = r.plugins.get("skills", [])
    def skill_line(e) -> str:
        whose = "built in" if e.source == "builtin" else "the user's own"
        state = "" if e.status == "ok" else f", {e.status}"
        return f"{e.name} ({whose}{state}): {e.description}"
    out.append(_section("Skills (loaded on demand)", [skill_line(e) for e in skills]))
    servers = r.plugins.get("servers", [])
    out.append(_section("Connected apps (MCP)", [
        f"{e.name} ({e.status if e.enabled else 'off'}): {e.description or 'no description'}"
        + (f"; tools: {', '.join(e.tools)}" if e.tools else "") for e in servers]))
    chat = resolve_selection(store, "chat")
    where = lambda s: "on this computer" if not s.leaves_mini else "cloud"  # noqa: E731
    out.append(_section("Models", [
        f"Model: {chat.model} via {chat.provider.name} ({where(chat)}), for chat and the background work (brief, memory review, trackers)",
        "Providers connected: " + ", ".join(p.name for p in all_providers(store))]))
    engine, v = voice.get_tts(store)
    talk = "Talk (live voice) is available" if engine == "openai" or voice.load_secret("OPENAI_API_KEY") else "Talk needs an OpenAI key"
    out.append(_section("Voice", [f"Read-aloud: {voice.ENGINES[engine]['label']} ({v})", talk]))
    active = [t for t in trackers.listing(store) if t["status"] in ("active", "paused")]
    from odie.trackers.signed_in import shown_summary
    out.append(_section("Trackers", [f"{t['title']} ({t['status']}): {shown_summary(t) or 'no result yet'}" for t in active]))
    out.append(_section("Runs on its own", list(schedule().values())))
    out.append(_section("Visual blocks it can draw", [", ".join(sorted(kinds()))]))
    out.append(_section("Phone and other devices", phone_lines(store)))
    out.append(_section("How to add more", EXTEND))
    return "\n\n".join(out)
