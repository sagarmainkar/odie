"""The loop eval's entry point (scripts/loops_eval.sh): the made-up cases in evals/loops/cases through the real
watch turn and the real stage 4, on a throwaway home, with a fake gh answering from each case. As odie/watch_eval.py,
it points every Odie folder at the throwaway home before anything loads Odie's settings.

    scripts/loops_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
    scripts/loops_eval.sh anthropic/claude-sonnet-5-5 fourteen-mails-one-pr    (one case by id)"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from odie.blocks_eval import commit_of_repo, copy_key, file_stem, key_name_for, owner_env_file, use_throwaway_home


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

    async def turn(prompt, tools, instruction):
        await runner.background_turn(prompt, timeout=280, tools=tools, instruction=instruction, guard=watch_check.guard)

    async def think(prompt, instruction):
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
    out = loops_eval.EVAL_DIR / f"{file_stem(date, provider, model)}.json"
    out.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    t = run["totals"]
    print(f"right {t['right']}/{t['of']} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
