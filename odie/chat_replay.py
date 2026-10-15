"""Replays a test conversation through another model, so the chats can be watched side by side (2026-10-11).

The blocks eval (odie/blocks_eval.py) asks single questions, each in a fresh chat. This sends a fixed list of user turns
in ONE chat, as the owner typed them, so follow-ups like "yes" lean on what came before. It runs on a throwaway home,
like the blocks eval, with only these read from Odie's own folder (~/.odie, or ODIE_HOME), never written:
  - the provider's API key and the web search key (TAVILY_API_KEY), from its .env, copied into this process only;
  - the persona: SOUL.md, copied into the throwaway home, and the user's and assistant's names, read from its database
    and set the way setup sets them, so the system prompt matches the live one.
Each turn records the reply, the tools called (with short arguments), whether the old visuals skill was loaded (before
12 Oct 2026; the catalogue is in the system prompt since), the time and the tokens. The web app's own Markdown and
block parsers then score each reply (web/scripts/score-chat.mjs): what it drew, what it dropped, and any fence-looking
text the chat would NOT draw. Results go to
evals/chats/<date>-<provider>-<model>.json with a short .md (not committed; the app's #sample screen shows evals/sample).

    scripts/chat_replay.sh anthropic/claude-sonnet-5-5
    scripts/chat_replay.sh anthropic/claude-sonnet-5-5 --turns evals/chats/2026-10-11-test-chat.turns.json
    scripts/chat_replay.sh --import-session chat-2026-10-11 --label lmstudio/gemma-4-26b-a4b-it-qat
    scripts/chat_replay.sh --rescore        (score every saved chat again, after a parser change; no model calls)"""
from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from odie import blocks_eval as be

REPO = be.REPO
RESULTS_DIR = Path(os.environ.get("CHAT_REPLAY_DIR") or REPO / "evals" / "chats")  # CHAT_REPLAY_DIR: a trial run elsewhere
DEFAULT_TURNS = REPO / "evals" / "chats" / "2026-10-11-test-chat.turns.json"
SEARCH_KEY = "TAVILY_API_KEY"  # the live install searches the web with Tavily
SHORT_ARG = 120  # characters of each tool argument kept in the results
CHECK_PREFIX = "[odie check] "  # the runner's own nudge, never something the user said (odie.app.runner.CHECK_PREFIX)


# ── The turns ───────────────────────────────────────────────────────────────────────────────────────────────────────

def load_turns(path: Path) -> dict:
    """The conversation to replay: {"id", "about", "turns": [the user's messages, in order]}.
    Every turn must be a non-empty string; anything else stops the run before a model is called.
      {"id": "t", "turns": ["What can you do?", "yes"]} → the same, with "about" "" when it has none
      {"id": "t", "turns": ["ok", ""]}                   → ValueError (turn 2 is empty)"""
    data = json.loads(path.read_text())
    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError(f"{path}: no turns")
    for i, t in enumerate(turns, 1):
        if not isinstance(t, str) or not t.strip():
            raise ValueError(f"{path}: turn {i} is empty or not text")
    return {"id": str(data.get("id") or path.stem), "about": str(data.get("about") or ""), "turns": turns}


def short_args(args: dict) -> dict:
    """A tool call's arguments, each text cut to SHORT_ARG characters, so a results file stays readable.
      {"query": "Pixel 10a price", "max_results": 5} → the same;  {"script": <2,000 characters>} → its first 120 + "…" """
    out = {}
    for name, value in (args or {}).items():
        if isinstance(value, str) and len(value) > SHORT_ARG:
            value = value[:SHORT_ARG] + "…"
        out[name] = value
    return out


def podcast_hosts(script: str) -> list[str]:
    """The host names in a podcast script ("Name: what they say" per line), each once, in the order they speak.
      "Asha: Welcome!\\nRohan: Hi.\\nAsha: So…" → ["Asha", "Rohan"];  "just words" → [] """
    hosts: list[str] = []
    for line in script.splitlines():
        name, sep, _ = line.partition(":")
        name = name.strip()
        if sep and name and len(name) <= 30 and name not in hosts:
            hosts.append(name)
    return hosts


def tool_record(name: str, args: dict) -> dict:
    """One tool call for the results: its name and short arguments, plus the hosts when it made a podcast."""
    record = {"tool": name, "args": short_args(args)}
    if name == "speak" and str(args.get("style") or "").lower() == "podcast":
        record["hosts"] = podcast_hosts(str(args.get("script") or ""))
    return record


def loaded_visuals(tools: list[dict]) -> bool:
    """Whether the turn opened the visuals skill (the one that taught the blocks until 12 Oct 2026; since then the
    catalogue is in the system prompt, so a replay records False and the chat says visuals_in_prompt).
      [{"tool": "load_skill", "args": {"skill_name": "visuals"}}] → True;  [{"tool": "web_search", …}] → False"""
    for t in tools:
        if t["tool"] == "load_skill" and (t.get("args") or {}).get("skill_name") == "visuals":
            return True
    return False


# ── The owner's persona and keys (read only) ───────────────────────────────────────────────────────────────────────

def owner_home() -> Path:
    """Odie's own folder, where the persona and keys are read from: ODIE_HOME, else ~/.odie."""
    return Path(os.environ.get("ODIE_HOME") or "~/.odie").expanduser()


def read_only(db: Path) -> sqlite3.Connection:
    """A SQLite connection that cannot write (mode=ro): the owner's live databases are only ever read."""
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def owner_names(db: Path) -> dict:
    """The user's and the assistant's names, as setup saved them in the owner's database (read only).
      settings profile {"user_name": "Asha"}, persona {"name": "Iris"} → {"user_name": "Asha", "assistant_name": "Iris"}
      no such rows → {"user_name": "", "assistant_name": ""} (the replay then keeps Odie's defaults)"""
    names = {"user_name": "", "assistant_name": ""}
    if not db.exists():
        return names
    with read_only(db) as conn:
        rows = dict(conn.execute("select key, value_json from settings where key in ('profile', 'persona')").fetchall())
    profile = json.loads(rows.get("profile") or "{}")
    persona = json.loads(rows.get("persona") or "{}")
    names["user_name"] = profile.get("user_name") or ""
    names["assistant_name"] = persona.get("name") or ""
    return names


def copy_persona(source_home: Path, home: Path, store, names: dict) -> bool:
    """Gives the throwaway home the owner's persona: SOUL.md copied in, and the names set the way setup sets them
    (odie.setup.tools.set_names). True when there was a SOUL.md to copy."""
    from odie.setup.tools import set_names
    soul = source_home / "SOUL.md"
    copied = soul.is_file()
    if copied:
        home.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(soul, home / "SOUL.md")
    if names["user_name"]:
        asyncio.run(set_names(store, names["user_name"], names["assistant_name"] or None))
    return copied


def first_live_system_prompt(requests_dir: Path) -> str:
    """The system prompt of the oldest request the live install saved (data/requests keeps the last few), or ""."""
    files = sorted(requests_dir.glob("*.json"))
    if not files:
        return ""
    body = json.loads(files[0].read_text())
    for m in body.get("messages") or []:
        if m.get("role") == "system" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


def prompt_differences(live: str, replay: str) -> list[str]:
    """The lines that differ between the live system prompt and the replay's, "- " for live only, "+ " for the replay
    only, each cut to 160 characters; blank lines don't count. Same prompts → [].
      live "A\\nB\\nC", replay "A\\nC\\nD" → ["- B", "+ D"]"""
    out = []
    for line in difflib.ndiff(live.splitlines(), replay.splitlines()):
        if line[:2] in ("- ", "+ ") and line[2:].strip():
            out.append(line[:160])
    return out


def prompt_catcher():
    """A plugin that keeps the system prompt of the first model call, exactly as it is sent (Odie's prompt plus what
    ADK adds, such as the skills list), to compare with the live install's saved request."""
    from google.adk.plugins.base_plugin import BasePlugin

    class PromptCatcher(BasePlugin):
        def __init__(self):
            super().__init__(name="chat_replay_prompt")
            self.text = ""

        async def before_model_callback(self, *, callback_context, llm_request):
            if not self.text:
                self.text = system_text(llm_request.config.system_instruction)
            return None

    return PromptCatcher()


def system_text(instruction) -> str:
    """A request's system instruction as plain text: a string as it is, a Content's text parts joined, nothing → ""."""
    if instruction is None:
        return ""
    if isinstance(instruction, str):
        return instruction
    parts = getattr(instruction, "parts", None) or []
    return "".join(p.text or "" for p in parts)


# ── Asking the turns ───────────────────────────────────────────────────────────────────────────────────────────────

def turn_record(n: int, user: str, asked: dict) -> dict:
    """One turn for the results, from what blocks_eval.ask_in gave back."""
    tools = [tool_record(t["tool"], t.get("args") or {}) for t in asked["tools"]]
    return {"n": n, "user": user, "reply": asked["reply"], "tools": tools, "visuals": loaded_visuals(tools),
            "media": asked.get("media") or [], "events": asked["events"], "error": asked["error"],
            "seconds": asked["seconds"], "tokens": asked["tokens"]}


async def run_turns(provider: str, model: str, turns: list[str], session_id: str, thinking: bool = False) -> dict:
    """Every turn through a real OdieRunner set to this model, all in one chat. Call only after the throwaway home is
    set up. A turn that errors is recorded and the next one is still sent, as the owner would."""
    from odie import config
    from odie.app.runner import OdieRunner
    from odie.models import all_providers
    from odie.store.db import Store

    store = Store(config.settings.db_path)
    store.init_schema()
    known = [p.id for p in all_providers(store)]
    if provider not in known:
        raise SystemExit(f"No provider {provider!r} here (known: {', '.join(known)}). Is its key in Odie's .env?")
    store.set_setting("model.chat", {"provider": provider, "model": model})
    runner = OdieRunner(store)
    runner.review_every = 10**6  # no memory review between turns, as in the blocks eval: it is an extra model call
    await runner.load_plugins()
    counter = be.token_counter()
    runner.runner.plugin_manager.register_plugin(counter)
    catcher = prompt_catcher()
    runner.runner.plugin_manager.register_plugin(catcher)
    records = []
    try:
        for n, text in enumerate(turns, 1):
            print(f"  {n:>2}. {text[:60]!r}: ", end="", flush=True)
            asked = await be.ask_in(runner, text, session_id, counter, thinking=thinking)
            tail = f", {asked['error']}" if asked["error"] else ""
            print(f"{asked['seconds']} s, {len(asked['reply'])} chars, {len(asked['tools'])} tools{tail}", flush=True)
            records.append(turn_record(n, text, asked))
    finally:
        await runner.close()
        from odie.browser import close_shared
        await close_shared()
    return {"provider": provider, "model": model, "turns": records, "system_prompt": catcher.text}


# ── Importing a live chat (read only) ──────────────────────────────────────────────────────────────────────────────

def visible_user_text(text: str) -> tuple[str, int]:
    """What the user typed, as the chat shows it, and how many pictures came with it: Odie's own trailer (the
    "[context: …]" note, prefetched blocks) and the [image:id] markers are taken off, with the app's own helpers.
      "yes\\n\\n[context: now 18:19 Sun 11 Oct]" → ("yes", 0)
      "I see json\\n[image:871a5acbefc94de3]\\n\\n[context: …]" → ("I see json", 1)"""
    from odie.app.runner import split_images, strip_trailer
    clean, images = split_images(strip_trailer(text))
    return clean, len(images)


def import_session(db: Path, session_id: str) -> list[dict]:
    """A saved chat, read only from an ADK sessions database, as turns in the replay's format. A turn starts at each
    message the user typed (the runner's own "[odie check]" nudges stay in the turn they belong to) and holds every
    model step until the next one: text pieces, tool calls in order, what the tools made, the time to the last step
    and the tokens the model reported."""
    with read_only(db) as conn:
        rows = conn.execute("select timestamp, event_data from events where session_id = ? order by timestamp",
                            (session_id,)).fetchall()
    turns: list[dict] = []
    current: dict | None = None
    pieces: list[str] = []
    for ts, raw in rows:
        event = json.loads(raw)
        parts = (event.get("content") or {}).get("parts") or []
        if event.get("partial"):
            continue
        if event.get("author") == "user":
            said = "".join(p.get("text") or "" for p in parts)
            is_typed = bool(said) and not said.startswith(CHECK_PREFIX)
            if is_typed:
                if current is not None:
                    current["reply"] = be.reply_from(pieces)
                text, images = visible_user_text(said)
                current = {"n": len(turns) + 1, "user": text, "images": images, "reply": "", "tools": [], "visuals": False,
                           "media": [], "events": [], "error": None, "started": ts, "seconds": 0.0,
                           "tokens": {"input": 0, "cached": 0, "output": 0, "calls": 0}}
                pieces = []
                turns.append(current)
                continue
        if current is None:
            continue
        current["seconds"] = round(ts - current["started"], 1)
        add_model_step(current, event, parts, pieces)
    if current is not None:
        current["reply"] = be.reply_from(pieces)
    for t in turns:
        t.pop("started")
        t["visuals"] = loaded_visuals(t["tools"])
    return turns


def add_model_step(turn: dict, event: dict, parts: list[dict], pieces: list[str]) -> None:
    """Adds one saved event to its turn: text to the reply pieces, calls to the tools, made media, the usage."""
    for p in parts:
        call = p.get("function_call")
        response = p.get("function_response")
        if call and call.get("name") != "adk_request_confirmation":
            turn["tools"].append(tool_record(call["name"], call.get("args") or {}))
        elif response:
            made = (response.get("response") or {}).get("media")
            if isinstance(made, dict):
                turn["media"].append({"kind": made.get("kind"), "title": made.get("title")})
        elif p.get("text") and event.get("author") != "user" and not p.get("thought"):
            pieces.append(p["text"])
    usage = event.get("usage_metadata")
    if usage:
        turn["tokens"]["input"] += usage.get("prompt_token_count") or 0
        turn["tokens"]["cached"] += usage.get("cached_content_token_count") or 0
        turn["tokens"]["output"] += usage.get("candidates_token_count") or 0
        turn["tokens"]["calls"] += 1


# ── Saving and scoring ─────────────────────────────────────────────────────────────────────────────────────────────

def score_with_app_parser(path: Path) -> None:
    """Fills each turn's "score" with the web app's own Markdown and block parsers (web/scripts/score-chat.mjs)."""
    subprocess.run(["node", str(REPO / "web" / "scripts" / "score-chat.mjs"), str(path)], cwd=REPO / "web", check=True)


def totals(turns: list[dict]) -> dict:
    """The whole chat's time and tokens: the sum over its turns."""
    out = {"seconds": 0.0, "input": 0, "cached": 0, "output": 0, "calls": 0, "errors": 0}
    for t in turns:
        out["seconds"] = round(out["seconds"] + t["seconds"], 1)
        for k in ("input", "cached", "output", "calls"):
            out[k] += t["tokens"].get(k, 0)
        if t["error"]:
            out["errors"] += 1
    return out


def what_it_did(turn: dict) -> str:
    """One turn in a few words, for the summaries: what it drew, else plain text, and the tools; or the error.
      kinds ["table"], tools [web_search, load_skill] → "table · web_search, load_skill"
      no kinds, not drawn ["inline code"]           → "plain text, 1 not drawn (inline code)"
      error "no reply in 240 s"                     → "error: no reply in 240 s" """
    if turn["error"] and not turn["reply"]:
        return f"error: {turn['error']}"
    score = turn.get("score") or {}
    kinds = score.get("kinds") or []
    words = ", ".join(dict.fromkeys(kinds)) if kinds else "plain text"
    not_drawn = score.get("not_drawn") or []
    if not_drawn:
        how = ", ".join(dict.fromkeys(x["as"] for x in not_drawn))
        words += f", {len(not_drawn)} not drawn ({how})"
    tools = ", ".join(dict.fromkeys(t["tool"] for t in turn["tools"]))
    if tools:
        words += f" · {tools}"
    return words


def chat_markdown(chat: dict, stem: str) -> str:
    """A short summary of one chat: where it came from, its totals, then each turn in a line."""
    t = chat["totals"]
    where = "live chat, imported" if chat.get("source") == "live" else f"replay on Odie {chat.get('odie_commit') or '?'}"
    lines = [f"# Chat: `{chat['provider']}/{chat['model']}`", "",
             f"{chat['date']} · {where} · {len(chat['turns'])} turns · {t['seconds']:.0f} s · "
             f"{t['input'] / 1000:.0f}k tokens in, {t['output'] / 1000:.1f}k out · {t['errors']} errors · `{stem}.json`", "",
             "| # | User | What it did | Time |", "|---|---|---|---|"]
    for turn in chat["turns"]:
        user = turn["user"].replace("\n", " ").replace("|", "/")[:70]
        lines.append(f"| {turn['n']} | {user} | {what_it_did(turn).replace('|', '/')} | {turn['seconds']} s |")
    return "\n".join(lines) + "\n"


def save_chat(chat: dict, stem: str) -> Path:
    """Writes the chat, scores it with the app's parsers, and writes its summary next to it."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{stem}.json"
    path.write_text(json.dumps(chat, ensure_ascii=False, indent=2) + "\n")
    score_with_app_parser(path)
    chat = json.loads(path.read_text())
    (RESULTS_DIR / f"{stem}.md").write_text(chat_markdown(chat, stem))
    return path


def saved_chats(results_dir: Path) -> list[Path]:
    """The results files in the folder: every .json but the turn lists (*.turns.json)."""
    return [p for p in sorted(results_dir.glob("*.json")) if not p.name.endswith(".turns.json")]


def rescore_all(results_dir: Path) -> None:
    for path in saved_chats(results_dir):
        score_with_app_parser(path)
        chat = json.loads(path.read_text())
        (results_dir / f"{path.stem}.md").write_text(chat_markdown(chat, path.stem))


# ── The command ────────────────────────────────────────────────────────────────────────────────────────────────────

def option(argv: list[str], name: str) -> str | None:
    """The value after `name` in the arguments: (["--label", "x/y"], "--label") → "x/y"; missing → None."""
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def import_main(argv: list[str]) -> int:
    session_id = option(argv, "--import-session")
    label = option(argv, "--label")
    if not session_id or not label or "/" not in label:
        print("usage: scripts/chat_replay.sh --import-session <session id> --label <provider>/<model> [--db sessions.db]")
        return 2
    provider, model = label.split("/", 1)
    db = Path(option(argv, "--db") or owner_home() / "data" / "sessions.db")
    # Odie's helpers that clean the user's text load Odie's settings: point them at a throwaway home first, so even
    # that never opens the owner's folder for writing. The sessions database itself is opened read only.
    be.use_throwaway_home(Path(tempfile.mkdtemp(prefix="odie-chat-import-")))
    turns = import_session(db, session_id)
    if not turns:
        print(f"No turns in session {session_id!r} of {db}")
        return 1
    date = session_date(session_id) or datetime.now().strftime("%Y-%m-%d")
    chat = {"kind": "chat", "source": "live", "date": date, "provider": provider, "model": model, "session": session_id,
            "turns": turns, "totals": totals(turns)}
    path = save_chat(chat, be.file_stem(date, provider, model))
    print(f"{len(turns)} turns → {path}")
    return 0


def session_date(session_id: str) -> str:
    """The date in a chat's session id: "chat-2026-10-11" → "2026-10-11"; "eval-x" → "" """
    found = re.search(r"\d{4}-\d{2}-\d{2}", session_id)
    if found:
        return found.group(0)
    return ""


def replay_main(argv: list[str]) -> int:
    provider, model = argv[0].split("/", 1)
    turns_file = Path(option(argv, "--turns") or DEFAULT_TURNS)
    conversation = load_turns(turns_file)
    thinking = "--thinking" in argv  # the chat's "think longer" toggle on, as the app starts

    # Step 1: everything read from the owner's folder, before this process points at the throwaway home.
    source = owner_home()
    keys_from = source / ".env"
    names = owner_names(source / "data" / "assistant.db")
    live_prompt = first_live_system_prompt(source / "data" / "requests")

    # Step 2: the throwaway home, then the keys, the persona and the model.
    root = Path(tempfile.mkdtemp(prefix="odie-chat-replay-"))
    be.use_throwaway_home(root)
    key_name = be.key_name_for(provider)
    if key_name and not be.copy_key(key_name, keys_from):
        print(f"No {key_name} in {keys_from} or the environment: {provider} can't be reached.")
        return 1
    has_search = be.copy_key(SEARCH_KEY, keys_from)
    from odie import config
    from odie.store.db import Store
    store = Store(config.settings.db_path)
    store.init_schema()
    soul = copy_persona(source, config.settings.config_dir, store, names)
    print(f"Chat replay: {provider}/{model}{' (think longer on)' if thinking else ''}, {len(conversation['turns'])} turns in one chat, throwaway home {root}"
          f" (persona: SOUL {'copied' if soul else 'none'}, user {names['user_name'] or '-'},"
          f" assistant {names['assistant_name'] or '-'}; web search key {'copied' if has_search else 'missing'})")

    # Step 3: the turns, through the real runner.
    date = datetime.now().strftime("%Y-%m-%d")
    run = asyncio.run(run_turns(provider, model, conversation["turns"], f"replay-{date}", thinking))
    system_prompt = run.pop("system_prompt")
    chat = {"kind": "chat", "source": "replay", "date": date, "odie_commit": be.commit_of_repo(), "visuals_in_prompt": True, **run,
            "conversation": conversation["id"], "settings": {"thinking": thinking, "web_search_key": has_search},
            "prompt_vs_live": prompt_differences(live_prompt, system_prompt) if live_prompt else None,
            "totals": totals(run["turns"])}

    # Step 4: save, score with the app's parsers, summarise.
    stem = be.file_stem(date, provider, model)
    if thinking:
        stem += "-think-longer"  # kept beside the same model's run with the toggle off
    path = save_chat(chat, stem)
    t = chat["totals"]
    print(f"{t['seconds']:.0f} s, {t['input'] / 1000:.0f}k in, {t['output'] / 1000:.1f}k out, {t['errors']} errors → {path}")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--rescore"]:
        rescore_all(RESULTS_DIR)
        return 0
    if argv and argv[0] == "--import-session":
        return import_main(argv)
    if not argv or "/" not in argv[0]:
        print("usage: scripts/chat_replay.sh <provider>/<model> [--turns file]   e.g. anthropic/claude-sonnet-5-5\n"
              "       scripts/chat_replay.sh --import-session chat-2026-10-11 --label lmstudio/gemma-4-26b-a4b-it-qat\n"
              "       scripts/chat_replay.sh --rescore")
        return 2
    return replay_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
