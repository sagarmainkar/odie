"""The watch eval's entry point (scripts/watch_eval.sh): it points every Odie folder at a throwaway home BEFORE
anything loads Odie's settings, then runs odie.watch.eval. Odie's settings are made when odie.config is first imported,
so nothing from Odie (except odie.blocks_eval, which imports none of it at the top) is imported at the top here.

    scripts/watch_eval.sh ollama/deepseek-v4.1-flash:1017-cloud
    scripts/watch_eval.sh anthropic/claude-sonnet-5-5 invite-from-a-person    (one case by id)"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from odie.blocks_eval import commit_of_repo, copy_key, file_stem, key_name_for, owner_env_file, use_throwaway_home


def main(argv: list[str]) -> int:
    if not argv or "/" not in argv[0]:
        print("usage: scripts/watch_eval.sh <provider>/<model> [case ids…]")
        return 2
    provider, model = argv[0].split("/", 1)

    # Step 1: the key, read from the owner's .env before anything points at the throwaway home; then the home.
    keys_from = owner_env_file()
    root = Path(tempfile.mkdtemp(prefix="odie-watch-eval-"))
    use_throwaway_home(root)
    key_name = key_name_for(provider)
    if key_name and not copy_key(key_name, keys_from):
        print(f"No {key_name} in {keys_from}: {provider} can't be reached.")
        return 1

    # Step 2: the cases, through the real watch turn (odie.watch.eval loads Odie's settings: only now).
    from odie.watch import eval as watch_eval
    cases = watch_eval.load_cases()
    if len(argv) > 1:
        cases = [c for c in cases if c["id"] in argv[1:]]
    print(f"Watch eval: {provider}/{model}, {len(cases)} cases, throwaway home {root}")
    results = asyncio.run(watch_eval.run_all(provider, model, cases))
    date = datetime.now().strftime("%Y-%m-%d")
    run = {"date": date, "odie_commit": commit_of_repo(), "provider": provider, "model": model,
           "totals": watch_eval.totals(results), "results": results}

    # Step 3: save and summarise.
    out_dir = watch_eval.EVAL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem(date, provider, model)
    (out_dir / f"{stem}.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    (out_dir / f"{stem}.md").write_text(watch_eval.run_markdown(run))
    t = run["totals"]
    print(f"right {t['right']}/{t['of']}, opened {t['opened_when_needed']}/{t['must_open']} -> {out_dir / stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
