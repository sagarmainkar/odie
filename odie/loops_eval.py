"""The loop eval's entry point (scripts/loops_eval.sh): the made-up cases in evals/loops/cases through the real
watch turn and the real stage 4, on a throwaway home, with a fake gh answering from each case. As odie/watch_eval.py,
it points every Odie folder at the throwaway home before anything loads Odie's settings.

    scripts/loops_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
    scripts/loops_eval.sh anthropic/claude-sonnet-5-5 fourteen-mails-one-pr    (one case by id)
    scripts/loops_eval.sh ollama/deepseek-v4.1-flash:1017-cloud --tag=phase3   (kept under its own file name)"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from odie.blocks_eval import commit_of_repo, copy_key, file_stem, key_name_for, owner_env_file, use_throwaway_home


def keeps_for_eval(name: str) -> bool:
    """Stage 1's allow-list for the eval, less every tool of this Mac (its Mail, Calendar, Reminders: mac_*): the eval's
    sources are the cases' made-up mail and events (EvalFetcher), and its calendar the recording fakes, so nothing of
    the owner's own is ever read or written. "calendar_create_event" (the fake) -> True; "mac_calendar_add" -> False."""
    from odie.watch import check as watch_check
    return watch_check.stage1_keeps(name) and not name.startswith("mac_")


async def declared_names(tools: list) -> set[str]:
    """The tool names a turn would be told about (toolsets asked with no skill loaded)."""
    from types import SimpleNamespace

    from google.adk.tools.base_toolset import BaseToolset
    context = SimpleNamespace(state={}, agent_name="odie_tracker", invocation_id="eval-check")
    names = set()
    for t in tools:
        if isinstance(t, BaseToolset):
            names |= {x.name for x in await t.get_tools(context)}
        else:
            names.add(t.name)
    return names


def refuse_mac(guard):
    """The watch's guard with every tool of this Mac refused too (a second lock beside keeps_for_eval)."""
    def eval_guard(tool, args, tool_context):
        if tool.name.startswith("mac_"):
            return {"error": "Not in the eval: this Mac's own apps are never used."}
        return guard(tool, args, tool_context)
    return eval_guard


async def run_all(provider: str, model: str, cases: list[dict], root: Path) -> list[dict]:
    from zoneinfo import ZoneInfo

    from odie import config
    from odie.app.runner import OdieRunner
    from odie.loops import eval as loops_eval
    from odie.models import all_providers
    from odie.store.db import Store
    from odie.watch import check as watch_check
    store = Store(config.settings.db_path)
    store.init_schema()
    if provider not in [p.id for p in all_providers(store)]:
        raise SystemExit(f"No provider {provider!r} here. Is its key in Odie's .env?")
    store.set_setting("model.chat", {"provider": provider, "model": model})
    runner = OdieRunner(store)
    runner.review_every = 10**6
    await runner.load_plugins()
    named = await declared_names(runner.stage_tools([], watch_check.MAY_WRITE, keeps_for_eval))
    mine = sorted(n for n in named if n.startswith("mac_"))
    if mine:  # never: the eval must not reach this Mac's Mail, Calendar or Reminders
        raise SystemExit(f"Stopped: stage 1 would be handed this Mac's own tools: {', '.join(mine)}")

    async def turn(prompt, tools, instruction, script=None):
        await runner.background_turn(prompt, timeout=280, tools=tools, instruction=instruction,
                                     guard=refuse_mac(watch_check.guard), keep=keeps_for_eval)

    async def think(prompt, instruction, script=None):  # the real model: a case's script is for the tests only
        return await runner.background_turn(prompt, timeout=120, instruction=instruction, bare=True)
    now = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo(config.settings.timezone))
    results = []
    try:
        for case in cases:
            folder = root / "cases" / case["id"]
            folder.mkdir(parents=True, exist_ok=True)
            r = await loops_eval.run_case(store, case, now, turn, think, folder)
            print(f"  {case['id']}: {r['score']['right']}/{r['score']['of']} {r['score']['wrong'] or ''}", flush=True)
            results.append(r)
    finally:
        await runner.close()
    return results


def main(argv: list[str]) -> int:
    if not argv or "/" not in argv[0]:
        print("usage: scripts/loops_eval.sh <provider>/<model> [case ids…]")
        return 2
    tag = ""
    for arg in list(argv):
        if arg.startswith("--tag="):  # a run kept under its own name: <date>-<provider>-<model>-<tag>.json
            tag = arg[len("--tag="):]
            argv = [a for a in argv if a != arg]
    provider, model = argv[0].split("/", 1)
    keys_from = owner_env_file()
    root = Path(tempfile.mkdtemp(prefix="odie-loops-eval-"))
    use_throwaway_home(root)
    key_name = key_name_for(provider)
    if key_name and not copy_key(key_name, keys_from):
        print(f"No {key_name} in {keys_from}: {provider} can't be reached.")
        return 1
    from odie.loops import eval as loops_eval
    cases = loops_eval.load_cases()
    if len(argv) > 1:
        cases = [c for c in cases if c["id"] in argv[1:]]
    results = asyncio.run(run_all(provider, model, cases, root))
    date = datetime.now().strftime("%Y-%m-%d")
    run = {"date": date, "odie_commit": commit_of_repo(), "provider": provider, "model": model,
           "totals": loops_eval.totals(results), "results": results}
    stem = file_stem(date, provider, model)
    if tag:
        stem += f"-{tag}"
    out = loops_eval.EVAL_DIR / f"{stem}.json"
    out.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    t = run["totals"]
    print(f"right {t['right']}/{t['of']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
