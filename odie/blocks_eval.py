"""Which models draw the new blocks well (composable blocks, step 5b; 2026-10-11).

Sends a fixed set of questions through Odie's real runner (its system prompt with the visual blocks, tools and skills), one
fresh chat per question, on a throwaway home: never Odie's own data. The only thing read from Odie's folder is the one
API key the chosen provider needs (from its .env, as scripts/model_check.sh does), copied into this process's
environment and never printed. Each reply is then scored with the app's own block parser (web/scripts/score-blocks.mjs)
and written to evals/blocks/<date>-<provider>-<model>.json, with a short Markdown summary next to it, and the grid in
evals/blocks/README.md is redrawn from every results file there.

    scripts/blocks_eval.sh ollama/glm-5.3-flash:cloud
    scripts/blocks_eval.sh anthropic/claude-sonnet-5-5
    scripts/blocks_eval.sh --rescore     (score the saved replies again, after a parser change; no model calls)"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(os.environ.get("BLOCKS_EVAL_DIR") or REPO / "evals" / "blocks")  # BLOCKS_EVAL_DIR: a trial run elsewhere
TURN_SECONDS = 240  # a turn still going after this is cut off and recorded as an error


@dataclass(frozen=True)
class Question:
    id: str
    ask: str
    expect: list[list[str]]  # every group needs one of its kinds drawn; [] means no blocks wanted
    nice: list[str] = field(default_factory=list)  # kinds that make it better, not required
    about: str = ""  # a few words for the grid


# Only public or made-up facts: no mail, money, notes, calendar, memory or signed-in sites.
QUESTIONS = [
    Question("phones", "Compare 3 good phones under ₹50,000 I can buy in India right now: price, camera and battery.",
             [["table"]], about="3 phones (table)"),
    Question("ooty-packing", "Make me a packing list for a weekend in Ooty.", [["checklist"]], about="Ooty packing (checklist)"),
    Question("home-loan", "Home loan what-if: ₹40 lakh at 8.5% for 20 years. What's the EMI, and let me play with the numbers.",
             [["calculator"]], about="home loan (calculator)"),
    Question("cafes", "Top 5 cafés in Koramangala?", [["list"]], about="cafés (list)"),
    # The first run asked only "Plan two days in Kyoto for me." and every model asked for dates and interests instead.
    Question("kyoto", "Plan two days in Kyoto for me: my first visit, mid-November, staying near Kyoto Station, "
             "temples and food, relaxed pace.", [["timeline"]], nice=["section"], about="Kyoto 2 days (timeline)"),
    Question("sip", "Compare SIPs of ₹5,000, ₹10,000 and ₹20,000 a month over 15 years at 12%.",
             [["calculator", "table", "chart"]], about="3 SIPs (calculator/table/chart)"),
    Question("monsoon-drive", "Is it safe to drive from Bangalore to Ooty in the monsoon?", [["callout"]],
             about="monsoon drive (callout)"),
    Question("laptops", "MacBook Air M5 or Dell XPS 13 for a student who codes? Compare them and tell me which to get.",
             [["table"], ["callout"]], nice=["section"], about="2 laptops (table + callout)"),
    Question("passport", "What are the steps to renew an Indian passport?", [["checklist"]], about="passport steps (checklist)"),
    # Two that need several answers before the model can help: a form, prefilled with its best guesses (26 Oct 2026).
    Question("weekend-trip", "Help me plan a weekend trip; ask me what you need to know first.", [["form"]], about="weekend trip (form)"),
    Question("story-video", "I want a short story video for my niece: ask me the choices.", [["form"]], about="story video (form)"),
    Question("capital", "What's the capital of Australia?", [], about="plain: capital"),
    Question("thanks", "Thanks, that's all for now!", [], about="plain: thanks"),
    Question("recursion", "Explain recursion in two lines.", [], about="plain: recursion"),
]


def owner_env_file() -> Path:
    """The .env holding the API keys: ODIE_HOME's (as scripts/model_check.sh sets it), else ~/.odie's."""
    home = os.environ.get("ODIE_HOME") or "~/.odie"
    return Path(home).expanduser() / ".env"


def throwaway_env(root: Path) -> dict[str, str]:
    """The environment that points every Odie folder into `root`, plus the switches that keep a run to itself.
    Example: root /tmp/odie-blocks-eval-x1 → ODIE_HOME=/tmp/odie-blocks-eval-x1/home, no add-ons (mail, money), no
    tracing upload, a keychain file of its own; India's time zone and locale, as Odie's owner uses it."""
    home = root / "home"
    return {
        "ODIE_HOME": str(home),
        "ODIE_DATA_DIR": str(home / "data"),
        "ODIE_CONFIG_DIR": str(home),
        "ODIE_MEMORY_FILE": str(home / "memories.md"),
        "ODIE_ADDONS": "",
        "ODIE_TRACE": "0",
        "LANGSMITH_TRACING": "false",
        "ODIE_KEYCHAIN": str(root / "no-keychain.keychain-db"),
        "ODIE_TIMEZONE": "Asia/Kolkata",
        "ODIE_LOCALE": "en-IN",
    }


def is_inside(path: str, root: Path) -> bool:
    """Whether a path lies in `root`: "/tmp/x/home/data" in /tmp/x → True; "/Users/me/.odie" in /tmp/x → False."""
    return Path(path).resolve().is_relative_to(root.resolve())


def use_throwaway_home(root: Path) -> None:
    """Points this process's Odie at a throwaway home inside `root`, then checks that Odie's settings really took it:
    a data, settings or memory folder outside `root` (say ~/.odie/data) stops the run before anything is written."""
    os.environ.update(throwaway_env(root))
    from odie import config
    folders = {"data": config.settings.data_dir, "settings": config.settings.config_dir, "memory": config.settings.memory_file}
    for what, folder in folders.items():
        if not is_inside(str(folder), root):
            raise SystemExit(f"Odie's {what} folder isn't the throwaway one: {folder}")


def key_name_for(provider: str) -> str | None:
    """The .env key a provider needs: "anthropic" → "ANTHROPIC_API_KEY"; "ollama" (on this computer) → None."""
    from odie.models import PRESET_BY_ID
    preset = PRESET_BY_ID.get(provider)
    if preset is None:
        return None
    return preset.env


def copy_key(name: str, env_file: Path) -> bool:
    """Puts one key from the owner's .env into this process's environment (already set there: kept). True when found."""
    from odie.secrets import load_secret
    value = load_secret(name, env_file_path=env_file)
    if not value:
        return False
    os.environ[name] = value
    return True


def file_stem(date: str, provider: str, model: str) -> str:
    """The results file's name: ("2026-10-11", "ollama", "glm-5.3-flash:cloud") → "2026-10-11-ollama-glm-5-3-flash-cloud"."""
    model_part = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return f"{date}-{provider}-{model_part}"


def commit_of_repo() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10)
    except OSError:
        return ""
    return out.stdout.strip()


def reply_from(pieces: list[str]) -> str:
    """The reply as the app shows it: each piece of text (a tool call in between starts a new one) on its own lines.
    The runner's own "done" text joins them with nothing in between, which glues a fence to the sentence before it:
      ["Here's a list:", "```odie-blocks\n[…]\n```"] → "Here's a list:\n\n```odie-blocks\n[…]\n```" """
    return "\n\n".join(p.strip("\n") for p in pieces if p.strip())


async def ask_in(runner, text: str, session_id: str, counter, thinking: bool = False) -> dict:
    """One user message through the runner, in the given chat: the reply, the tools it called (with their arguments),
    what they made (a podcast, a file), the stream's notes, how long it took, the tokens, or the error. The blocks
    eval asks each question in a chat of its own; the chat replay (odie/chat_replay.py) asks every turn in one.
    thinking: the chat's "think longer" toggle (the app starts with it on; the eval and replay default to off)."""
    tools: list[dict] = []
    events: list[str] = []
    made: list[dict] = []
    pieces: list[str] = []  # the reply's text, one piece per model step (a tool call in between starts a new one)
    reply = ""
    error = None
    counter.reset()
    started = time.perf_counter()

    async def consume() -> str:
        async for item in runner.chat(text, thinking=thinking, session_id=session_id):
            kind = item["type"]
            if kind == "tool_start":
                tools.append({"tool": item["tool"], "args": item.get("args") or {}})
            elif kind == "media":
                media = item.get("media") or {}
                made.append({"kind": media.get("kind"), "title": media.get("title")})
            elif kind == "approval":
                events.append(f"approval card: {item.get('tool')}")
            elif kind == "error":
                events.append(f"error: {item.get('message')}")
            elif kind == "text":
                pieces.append(item["text"])
            elif kind == "done":
                return reply_from(pieces)
        return reply_from(pieces)

    try:
        reply = await asyncio.wait_for(consume(), timeout=TURN_SECONDS)
    except TimeoutError:
        error = f"no reply in {TURN_SECONDS} s"
    except Exception as e:  # noqa: BLE001 (recorded for the results, the run goes on)
        error = f"{type(e).__name__}: {str(e)[:200]}"
    stream_errors = [e for e in events if e.startswith("error: ")]
    if error is None and stream_errors:
        error = stream_errors[0].removeprefix("error: ")
    return {"reply": reply, "tools": tools, "media": made, "events": events, "error": error,
            "seconds": round(time.perf_counter() - started, 1), "tokens": counter.totals()}


async def ask_one(runner, q: Question, counter) -> dict:
    """One question in a chat of its own: the reply, the tools it called, how long it took, the tokens, or the error."""
    a = await ask_in(runner, q.ask, f"eval-{q.id}", counter)
    return {"id": q.id, "ask": q.ask, "about": q.about, "expect": q.expect, "nice": q.nice, "reply": a["reply"],
            "tools": a["tools"], "events": a["events"], "error": a["error"], "seconds": a["seconds"], "tokens": a["tokens"]}


def token_counter():
    """A plugin that adds up each model call's tokens during a turn (input, cached input, output, calls)."""
    from google.adk.plugins.base_plugin import BasePlugin

    class TokenCounter(BasePlugin):
        def __init__(self):
            super().__init__(name="blocks_eval_tokens")
            self.reset()

        def reset(self) -> None:
            self.input = self.cached = self.output = self.calls = 0

        def totals(self) -> dict:
            return {"input": self.input, "cached": self.cached, "output": self.output, "calls": self.calls}

        async def after_model_callback(self, *, callback_context, llm_response):
            usage = getattr(llm_response, "usage_metadata", None)
            if getattr(llm_response, "partial", False) or usage is None:
                return None
            self.input += usage.prompt_token_count or 0
            self.cached += usage.cached_content_token_count or 0
            self.output += usage.candidates_token_count or 0
            self.calls += 1
            return None

    return TokenCounter()


async def run_questions(provider: str, model: str, questions: list[Question]) -> dict:
    """Every question through a real OdieRunner set to this model. Call only after the throwaway environment is set."""
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
    runner.review_every = 10**6  # no memory review between questions: it would be an extra model call
    await runner.load_plugins()   # as the app does at start (a throwaway home has no servers or user skills)
    counter = token_counter()
    runner.runner.plugin_manager.register_plugin(counter)
    answers = []
    try:
        for q in questions:
            print(f"  {q.id}: ", end="", flush=True)
            a = await ask_one(runner, q, counter)
            print(f"{a['seconds']} s, {len(a['reply'])} chars{', ' + a['error'] if a['error'] else ''}", flush=True)
            answers.append(a)
    finally:
        await runner.close()
        from odie.browser import close_shared
        await close_shared()
    return {"provider": provider, "model": model, "visuals_in_prompt": True, "questions": answers}  # the catalogue, always


def merged_run(saved: dict, fresh: dict) -> dict:
    """Today's saved run with the questions just asked again put in place (in the question set's order); the rest kept.
      saved [phones, kyoto (old)] + fresh [kyoto (new)] → [phones, kyoto (new)], with the fresh run's date and commit"""
    by_id = {q["id"]: q for q in saved["questions"]}
    for q in fresh["questions"]:
        by_id[q["id"]] = q
    order = [q.id for q in QUESTIONS]
    questions = sorted(by_id.values(), key=lambda q: order.index(q["id"]) if q["id"] in order else len(order))
    return {**saved, "date": fresh["date"], "odie_commit": fresh["odie_commit"], "questions": questions}


def score_with_app_parser(path: Path) -> None:
    """Fills each question's "score" and the run's "summary", using the web app's own parser."""
    subprocess.run(["node", str(REPO / "web" / "scripts" / "score-blocks.mjs"), str(path)], cwd=REPO / "web", check=True)


VERDICT_MARK = {"pass": "✓", "partial": "~", "fail": "✗"}


def cell_for(score: dict | None) -> str:
    """One grid cell: ✓ alone for a pass, else the mark and the first reason.
    {"verdict": "fail", "reasons": ["no callout"]} → "✗ no callout";  None (question not run) → "–" """
    if not score:
        return "–"
    mark = VERDICT_MARK[score["verdict"]]
    if score["verdict"] == "pass":
        return mark
    reason = score["reasons"][0] if score["reasons"] else ""
    return f"{mark} {reason}".strip()


def run_label(run: dict) -> str:
    return f"{run['provider']}/{run['model']}"


def latest_runs(results_dir: Path) -> list[dict]:
    """The newest results file of each model, in the order the models were first run."""
    by_model: dict[str, dict] = {}
    for path in sorted(results_dir.glob("*.json")):
        run = json.loads(path.read_text())
        by_model[run_label(run)] = run  # dated names sort oldest first, so the newest wins
    return list(by_model.values())


def score_line(run: dict) -> str:
    s = run.get("summary") or {}
    return f"{s.get('pass', 0)} ✓ · {s.get('partial', 0)} ~ · {s.get('fail', 0)} ✗ of {s.get('total', 0)}"


def grid_markdown(runs: list[dict]) -> str:
    """The model × question grid. Rows are questions (in the first run's order), columns are models."""
    if not runs:
        return "No runs yet."
    header = "| Question | " + " | ".join(f"`{run_label(r)}`" for r in runs) + " |"
    rule = "|---|" + "---|" * len(runs)
    lines = [header, rule]
    first = runs[0]["questions"]
    for q in first:
        cells = []
        for r in runs:
            match = next((x for x in r["questions"] if x["id"] == q["id"]), None)
            cells.append(cell_for(match.get("score") if match else None))
        lines.append(f"| {q.get('about') or q['id']} | " + " | ".join(cells) + " |")
    lines.append("| **Score** | " + " | ".join(score_line(r) for r in runs) + " |")
    times = []
    tokens = []
    for r in runs:
        seconds = sum(x["seconds"] for x in r["questions"])
        times.append(f"{seconds:.0f} s")
        inp = sum(x["tokens"]["input"] for x in r["questions"])
        out = sum(x["tokens"]["output"] for x in r["questions"])
        tokens.append(f"{inp / 1000:.0f}k in · {out / 1000:.1f}k out")
    lines.append("| Time, all questions | " + " | ".join(times) + " |")
    lines.append("| Tokens | " + " | ".join(tokens) + " |")
    return "\n".join(lines)


def run_markdown(run: dict, stem: str) -> str:
    """A short summary of one run: its score, then each question's verdict, kinds drawn, drops and timing."""
    lines = [f"# Blocks eval: `{run_label(run)}`", "",
             f"Run {run['date']} on Odie {run.get('odie_commit') or '?'} · {score_line(run)} · results: `{stem}.json`", "",
             "| Question | Verdict | Drawn | Dropped | Tools | Time |", "|---|---|---|---|---|---|"]
    for q in run["questions"]:
        s = q["score"]
        drawn = ", ".join(s["kinds"]) or "–"
        dropped = "; ".join(f"{d['path']} {d['why']}" for d in s["dropped"]) or "–"
        tools = ", ".join(t["tool"] for t in q["tools"]) or "–"
        lines.append(f"| {q['about']} | {cell_for(s)} | {drawn} | {dropped} | {tools} | {q['seconds']} s |")
    return "\n".join(lines) + "\n"


GRID_START = "<!-- grid:start (scripts/blocks_eval.sh redraws this part) -->"
GRID_END = "<!-- grid:end -->"


def with_grid(readme: str, grid: str) -> str:
    """The README with its grid part replaced, the rest kept; a README without the markers gets them at the end.
      "Intro\n<start>\nold\n<end>\nNotes" → "Intro\n<start>\nnew grid\n<end>\nNotes" """
    block = f"{GRID_START}\n{grid}\n{GRID_END}"
    if GRID_START in readme and GRID_END in readme:
        before = readme.split(GRID_START)[0]
        after = readme.split(GRID_END, 1)[1]
        return before + block + after
    if not readme.strip():
        readme = "# Blocks eval: which models draw the new blocks well\n"
    return readme.rstrip("\n") + "\n\n" + block + "\n"


def redraw_readme(results_dir: Path) -> None:
    readme = results_dir / "README.md"
    old = readme.read_text() if readme.exists() else ""
    readme.write_text(with_grid(old, grid_markdown(latest_runs(results_dir))))


def rescore_all(results_dir: Path) -> None:
    """Scores every saved run again with today's parser (after a parser or alias change), and redraws the summaries."""
    for path in sorted(results_dir.glob("*.json")):
        score_with_app_parser(path)
        run = json.loads(path.read_text())
        (results_dir / f"{path.stem}.md").write_text(run_markdown(run, path.stem))
    redraw_readme(results_dir)


def main(argv: list[str]) -> int:
    if argv == ["--rescore"]:
        rescore_all(RESULTS_DIR)
        return 0
    if not argv or "/" not in argv[0]:
        print("usage: scripts/blocks_eval.sh <provider>/<model> [question ids…]   e.g. ollama/glm-5.3-flash:cloud, "
              "anthropic/claude-sonnet-5-5; ids: " + ", ".join(q.id for q in QUESTIONS))
        return 2
    provider, model = argv[0].split("/", 1)
    questions = QUESTIONS
    if len(argv) > 1:
        questions = [q for q in QUESTIONS if q.id in argv[1:]]

    # Step 1: the key, read from the owner's .env before anything points at the throwaway home.
    keys_from = owner_env_file()
    root = Path(tempfile.mkdtemp(prefix="odie-blocks-eval-"))
    use_throwaway_home(root)
    key_name = key_name_for(provider)
    if key_name and not copy_key(key_name, keys_from):
        print(f"No {key_name} in {keys_from}: {provider} can't be reached.")
        return 1

    # Step 2: the questions, through the real runner.
    print(f"Blocks eval: {provider}/{model}, {len(questions)} questions, throwaway home {root}")
    run = asyncio.run(run_questions(provider, model, questions))
    date = datetime.now().strftime("%Y-%m-%d")
    run = {"date": date, "odie_commit": commit_of_repo(), **run}

    # Step 3: save, score with the app's parser, summarise.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = file_stem(date, provider, model)
    path = RESULTS_DIR / f"{stem}.json"
    if len(questions) < len(QUESTIONS) and path.exists():
        run = merged_run(json.loads(path.read_text()), run)
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    score_with_app_parser(path)
    run = json.loads(path.read_text())
    (RESULTS_DIR / f"{stem}.md").write_text(run_markdown(run, stem))
    redraw_readme(RESULTS_DIR)
    print(f"{score_line(run)} → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
