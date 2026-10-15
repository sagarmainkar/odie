"""Records the sample chat the app shows (#sample, from Settings): ten turns through real Odie on the demo home (Maya's
made-up notes, memories, mail and calendar from video/demo), on DeepSeek, saved and scored in the chat replay's format
as evals/sample/sample-chat.json. Nobody in it is real, so the file is public. Run it again after a change to the
blocks or the prompt, and read sample-chat.md to see what each turn drew.

    uv run python video/demo/make_home.py --root ~/odie-sample --model ollama/deepseek-v4.1-flash:cloud
    uv run python evals/sample/record.py [--root ~/odie-sample] [--model ollama/deepseek-v4.1-flash:cloud]

Needs video/demo (the demo home builder and the fake mail server). Keys: TAVILY_API_KEY from ~/.odie/.env into this
process only. Writes only under --root and evals/sample/."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "video" / "demo"))

# Each turn asks for something the blocks can show, with the details spelled out (a model asks back when a date or a
# budget is left open, and a question isn't much of a sample).
TURNS = [
    "What can you do?",
    "Plan the long weekend of 21 to 24 May in Yosemite for the two of us: a cabin, hikes, a day-by-day plan and a budget table for about $1,500.",
    "Anything in my inbox I need to deal with?",
    "Make a weekly after-school timetable for Lily: piano Wednesday 4:30, swimming Monday and Friday at 5, library Thursday after school, soccer Saturday 9am.",
    "How have Apple and Microsoft done over the past year? Which looks stronger right now?",
    "Draw me how Atlas's data flows: Salesforce and product usage into the warehouse, then the health score, then the weekly digest to account owners.",
    "Search for flights from SFO to Seattle on Friday 23 October in the evening, back Sunday night, for the two of us, and compare the three best options in a table.",
    "Split a $7,000 monthly budget across rent, food, Lily's school, travel, savings and fun. Show it as a donut.",
    "Show my gym attendance this month as a heat map: Monday, Wednesday and Friday every week, except the second week when I skipped the lot.",
    "Make me four flashcards on how Atlas's health score works.",
]


async def record(provider: str, model: str) -> Path:
    from odie import blocks_eval as be
    from odie import chat_replay as cr
    from odie import config
    from odie.store.db import Store
    from odie.vault.worker import VaultWorker
    store = Store(config.settings.db_path)
    store.init_schema()
    await VaultWorker(store).run_once()  # so search_notes finds the demo notes
    search = be.copy_key("TAVILY_API_KEY", Path("~/.odie/.env").expanduser())
    print(f"Recording on {config.settings.data_dir} with {provider}/{model}; web search key {'yes' if search else 'NO'}", flush=True)
    date = datetime.now().strftime("%Y-%m-%d")
    run = await cr.run_turns(provider, model, TURNS, f"sample-{date}-{datetime.now().strftime('%H%M%S')}")
    run.pop("system_prompt", None)
    chat = {"kind": "chat", "source": "replay", "date": date, "odie_commit": be.commit_of_repo(), "visuals_in_prompt": True, **run,
            "conversation": "sample-chat", "settings": {"thinking": False, "web_search_key": search}, "totals": cr.totals(run["turns"])}
    return cr.save_chat(chat, "sample-chat")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=Path("~/odie-sample"))
    ap.add_argument("--model", default="ollama/deepseek-v4.1-flash:cloud")
    args = ap.parse_args(argv)
    root = args.root.expanduser()
    from make_home import point_at, refuse_odie_home
    refuse_odie_home(root)
    if not (root / "home" / "mcp.json").is_file():
        raise SystemExit(f"No demo home at {root / 'home'}: run video/demo/make_home.py --root {root} first.")
    os.environ["CHAT_REPLAY_DIR"] = str(HERE)  # read when chat_replay is imported: the chat lands next to this script
    point_at(root)
    provider, model = args.model.split("/", 1)
    path = asyncio.run(record(provider, model))
    for t in json.loads(path.read_text())["turns"]:
        kinds = t.get("score", {}).get("kinds", [])
        print(f"  {t['n']}. drew {kinds or 'text'}; tools {[x['tool'] for x in t['tools']]}; {t['seconds']} s"
              f"{'; ERROR ' + t['error'] if t['error'] else ''}", flush=True)
    print("→", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
