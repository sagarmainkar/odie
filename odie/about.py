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

# What a new skill can build on, beyond the built-in abilities above: Odie's own tools, each with how to use it, shown
# when the tool is present. The skill builder's guide carries them (skill_kit), so a skill uses Odie's voice and files
# instead of reaching for something else (a video skill once narrated with macOS `say`, 16 Oct 2026).
SKILL_TOOLS = [
    (("speak",), ("Narration: speak(script) reads plain speech aloud in the voice above, up to about 4,000 "
                  "characters (some 4 minutes) a call; its result's `path` is the saved WAV file, kept, to hand to "
                  "ffmpeg. voice_name=\"Michael\" picks another voice of the same engine, only when the user asks. "
                  "A podcast with two hosts is make_podcast (the podcast skill), and a story with several voices, "
                  "sound or music is a skill's own tool, not speak")),
    (("attach_file",), ("Showing a file: attach_file(path) for a file in the workspace: a picture shows, a video (mp4, "
                        "webm, mov) or a sound (mp3, m4a, wav) plays under the reply, anything else is a download card; "
                        "50 MB at most")),
    (("make_file",), ("Making a file: make_file(name, content) for .csv, .md, .txt, .html, .json, .ics or .svg, as a card "
                      "under the reply")),
    (("run_shell",), ("Commands: run_shell(command, cwd) in zsh; the user approves each one, and each stops after 60 "
                      "seconds with at most 8 KB of output, so split long work into steps. Check a program is there "
                      "first (command -v ffmpeg) and work in the workspace folder")),
    (("browser_open",), "A real browser: browser_open(url), then browser_click, browser_type and browser_scroll"),
    (("find_images",), "Photos for covers and slides: find_images(query), each with the credit to use"),
    (("find_clips",), ("Stock video clips (Pexels, Pixabay): find_clips(query), each with its length and the credit "
                       "to use")),
    (("market_history",), "Prices: market_history(symbol, period), with a chart block"),
    (("make_research",), ("Research: make_research(topic, brief, sources) looks a question up on the web and in the "
                          "user's notes in the background and posts a report with its sources to the chat; for a "
                          "long read, hand it over instead of searching page after page in the skill")),
]

SKILL_RULES = [
    "Build on what's listed here first, and ask the user only about what isn't listed",
    ("Narration always uses the voice engine chosen in Settings, in the chosen voice unless the user asks for another, "
     "and then only one of that engine's voices; never macOS `say` or another speech tool. Another engine is the "
     "user's choice, in Settings > Voice"),
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


def voice_lines(store) -> list[str]:
    """What speaks, and where: the engine and voice that read-aloud and the speak tool use, whether the words stay on
    this computer, and that engine's other voices (only that engine's: switching engines is the user's choice)."""
    from odie import voice
    engine, vid = voice.get_tts(store)
    label = voice.ENGINES[engine]["label"]
    chosen = next(v for v in voice.engine_voices(engine) if v["id"] == vid)
    where = "on this computer" if voice.ENGINES[engine]["local"] else f"in the cloud: the text goes to {label}"
    has_key = bool(voice.load_secret("OPENAI_API_KEY"))
    talk = "Talk (live voice) is available" if engine == "openai" or has_key else "Talk needs an OpenAI key"
    return [f"Read-aloud and the speak tool: {label}, {voice.voice_summary(chosen)}, {where}",
            f"{label}'s voices: {voice.voices_text(engine)}",
            talk]


def app_lines(r) -> list[str]:
    """The connected apps (MCP servers): each one's state, what it is and its tools."""
    lines = []
    for e in r.plugins.get("servers", []):
        state = e.status if e.enabled else "off"
        tools = f"; tools: {', '.join(e.tools)}" if e.tools else ""
        lines.append(f"{e.name} ({state}): {e.description or 'no description'}{tools}")
    return lines


def model_lines(store) -> list[str]:
    from odie.models import all_providers, resolve_selection
    chat = resolve_selection(store, "chat")
    where = "on this computer" if not chat.leaves_mini else "cloud"
    return [f"Model: {chat.model} via {chat.provider.name} ({where}), for chat and the background work (brief, memory review, trackers)",
            "Providers connected: " + ", ".join(p.name for p in all_providers(store))]


def skill_kit() -> str:
    """What Odie has here for a new skill to build on, read live, for the skill builder's guide: the voice, the
    abilities and tools that are present (each with how to use it), the workspace, the models and apps, and the rules.
    A tool that isn't present here isn't listed: no make_file -> no "Making a file" line."""
    from odie.agent.tools.files import workspace
    r = hooks["runner"]
    store = r.store
    names = set(r._all_tool_names())
    built_in = [f"{label}: {text}" for label, tools, text in abilities() if any(t in names for t in tools)]
    own_tools = [text for tools, text in SKILL_TOOLS if any(t in names for t in tools)]
    files = [f"The workspace folder, where a skill's files go and attach_file reads from: {workspace()}"]
    parts = ["What Odie has here (read live). A skill builds on these:",
             _section("Voice", voice_lines(store)),
             _section("Abilities and tools", built_in + own_tools + files),
             _section("Models", model_lines(store)),
             _section("Connected apps (MCP)", app_lines(r)),
             _section("Rules", SKILL_RULES)]
    return "\n\n".join(parts)


def features() -> str:
    from odie import trackers
    from odie.blocks import kinds
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
    out.append(_section("Connected apps (MCP)", app_lines(r)))
    out.append(_section("Models", model_lines(store)))
    out.append(_section("Voice", voice_lines(store)))
    active = [t for t in trackers.listing(store) if t["status"] in ("active", "paused")]
    from odie.trackers.signed_in import shown_summary
    out.append(_section("Trackers", [f"{t['title']} ({t['status']}): {shown_summary(t) or 'no result yet'}" for t in active]))
    out.append(_section("Runs on its own", list(schedule().values())))
    out.append(_section("Visual blocks it can draw", [", ".join(sorted(kinds()))]))
    out.append(_section("Phone and other devices", phone_lines(store)))
    out.append(_section("How to add more", EXTEND))
    return "\n\n".join(out)
