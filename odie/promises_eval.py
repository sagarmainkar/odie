"""The promise eval's entry point (scripts/promises_eval.sh): the made-up turns in evals/promises/cases through the
gate and the real after-turn read, on a throwaway home. The read is one call with no tools at all, so nothing of this
Mac (its Mail, Calendar, Reminders, files) can be reached; the run stops if the call would be handed any tool. Only a
provider that needs no key (Ollama on this computer) or a key already in this process's environment is used: nothing
is copied from Odie's .env.

    scripts/promises_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
    scripts/promises_eval.sh ollama/deepseek-v4.1-flash:1017-cloud quoted-mail-promise   (one case by id)"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from odie.blocks_eval import commit_of_repo, file_stem, key_name_for, use_throwaway_home


async def run_all(provider: str, model: str, cases: list[dict], root: Path) -> list[dict]:
    from zoneinfo import ZoneInfo

    from odie import config
    from odie.app.runner import OdieRunner
    from odie.loops import chat_eval
    from odie.store.db import Store
    store = Store(config.settings.db_path)
    store.init_schema()
    store.set_setting("model.chat", {"provider": provider, "model": model})
    runner = OdieRunner(store)
    runner.review_every = 10**6

    async def think(prompt: str, instruction: str) -> str:  # bare: the call is handed no tool at all
        return await runner.background_turn(prompt, timeout=120, instruction=instruction, bare=True)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=ZoneInfo(config.settings.timezone))
    results = []
    try:
        for case in cases:
            case_store = Store(root / f"{case['id']}.db")
            case_store.init_schema()
            r = await chat_eval.run_case(case_store, case, now, think)
            print(f"  {case['id']}: {r['score']['right']}/{r['score']['of']} {r['score']['wrong'] or ''}", flush=True)
            results.append(r)
    finally:
        await runner.close()
    return results


def main(argv: list[str]) -> int:
    if not argv or "/" not in argv[0]:
        print("usage: scripts/promises_eval.sh <provider>/<model> [case ids…]")
        return 2
    provider, model = argv[0].split("/", 1)
    root = Path(tempfile.mkdtemp(prefix="odie-promises-eval-"))
    use_throwaway_home(root)  # first: nothing below may load Odie's own settings
    key_name = key_name_for(provider)
    if key_name and not os.environ.get(key_name):
        print(f"{provider} needs {key_name} in this environment; nothing is copied from Odie's .env.")
        return 1
    from odie.loops import chat_eval
    cases = chat_eval.load_cases()
    if len(argv) > 1:
        cases = [c for c in cases if c["id"] in argv[1:]]
    results = asyncio.run(run_all(provider, model, cases, root))
    date = datetime.now().strftime("%Y-%m-%d")
    run = {"date": date, "odie_commit": commit_of_repo(), "provider": provider, "model": model,
           "totals": chat_eval.totals(results), "results": results}
    out = chat_eval.EVAL_DIR / f"{file_stem(date, provider, model)}.json"
    out.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    t = run["totals"]
    print(f"right {t['right']}/{t['of']} ({t['cases_right']}/{t['cases']} cases) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
