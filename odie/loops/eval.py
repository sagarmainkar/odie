"""How well Odie keeps loops (proactive design §3, "drift when a prompt or model changes"): made-up, messy cases
(`evals/loops/cases/*.json`) through the watch's turn and stage 4, scored for loop count, closes with evidence, and
cards. Each case is its mails, what GitHub says (a fake gh answers from it) and what should come of it:
  {"loops": 1}                    one loop for the whole case (fourteen mails about one pull request)
  {"closed": ["example/app#50"]}  that loop closed, with a reason
  {"cards": [...]}, {"no_card": [...]}  which loops end as a card on Pulse, and which never do

run_case takes the turn and the model call as arguments: tests pass scripted ones (deterministic, so the code's part
is held to the score), and odie/loops_eval.py passes the real model (scripts/loops_eval.sh)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from odie.loops import clock, ledger, shortcut

REPO = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO / "evals" / "loops"
CASES_DIR = EVAL_DIR / "cases"
FAKE_GH = EVAL_DIR / "fake_gh.py"
PROMPT = "Run the watch check."


def load_cases() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]


def use_fake_gh(case: dict, folder: Path) -> None:
    """Points Odie's gh at the fake, answering from this case's "gh" (nothing reaches GitHub)."""
    import sys
    data, log, script = folder / "gh.json", folder / "gh.log", folder / "gh"
    data.write_text(json.dumps(case.get("gh") or {}))
    script.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_GH} \"$@\"\n")
    script.chmod(0o755)
    os.environ["ODIE_GH"] = str(script)
    os.environ["FAKE_GH_DATA"] = str(data)
    os.environ["FAKE_GH_LOG"] = str(log)


def loop_of_ref(store, ref: str) -> dict | None:
    """The case's loop that holds this ref, open or closed (the newest)."""
    for row in store.query("select id from loops order by id desc"):
        loop = ledger.get(store, row["id"])
        if ref in loop["refs"]:
            return loop
    return None


def score(case: dict, store) -> dict:
    """One case's result against what it expects (this module's notes): each expectation right or wrong, and what
    went wrong in words. 14 loops where 1 was wanted -> loops wrong ("14 loops, wanted 1"); #50 still open where it
    should close -> "example/app#50 not closed"."""
    expect = case.get("expect") or {}
    count = store.one("select count(*) n from loops")["n"]
    checks, wrong = 0, []
    if "loops" in expect:
        checks += 1
        if count != expect["loops"]:
            wrong.append(f"{count} loops, wanted {expect['loops']}")
    for ref in expect.get("closed", []):
        checks += 1
        loop = loop_of_ref(store, ref)
        if loop is None or loop["state"] not in ("closed", "dropped") or not loop["closed_why"]:
            wrong.append(f"{ref} not closed with a reason")
    for ref in expect.get("cards", []):
        checks += 1
        loop = loop_of_ref(store, ref)
        if loop is None or loop["state"] != "ready":
            wrong.append(f"{ref} has no card")
    for ref in expect.get("no_card", []):
        checks += 1
        loop = loop_of_ref(store, ref)
        if loop is not None and loop["state"] == "ready":
            wrong.append(f"{ref} has a card it shouldn't")
    return {"right": checks - len(wrong), "of": checks, "wrong": wrong, "loops": count}


async def run_case(store, case: dict, now: datetime, turn, think, folder: Path) -> dict:
    """One case end to end: its mails through the watch's turn (stages 1 and 2), then stage 4 for every loop that is
    due, then the score. turn(prompt, tools, instruction) and think(prompt, instruction) are the model's."""
    from odie.watch import check as watch_check
    from odie.watch.eval import EvalFetcher
    from odie.watch.tools import Check, watch_tools
    use_fake_gh(case, folder)
    store.execute("delete from loop_events")
    store.execute("delete from loops")
    check = Check(EvalFetcher(store, now, case))
    check.mails = await check.fetcher.new_mail()
    check.mail_read = True
    check.loop_of = shortcut.attach_known(store, "", check.mails, now)
    error = ""
    try:
        await turn(PROMPT, watch_tools(check), watch_check._instruction("", ""))
    except Exception as e:  # noqa: BLE001 (a failed case is recorded; the rest still run)
        error = f"{type(e).__name__}: {e}"[:200]
    ran = await clock.run(store, now, lambda pid: think, None, most=50)
    return {"id": case["id"], "error": error, "ran": ran, "score": score(case, store)}


def totals(results: list[dict]) -> dict:
    out = {"right": 0, "of": 0, "wrong": []}
    for r in results:
        out["right"] += r["score"]["right"]
        out["of"] += r["score"]["of"]
        out["wrong"] += [f"{r['id']}: {w}" for w in r["score"]["wrong"]]
    return out
