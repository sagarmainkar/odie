"""How well Odie reads promises in chat (phase 4): made-up turns (`evals/promises/cases/*.json`) through the gate and
the after-turn read (odie.loops.chat_read), scored for Odie's promises kept as loops, his commitments offered, their
due days, and nothing from quoted mail, a pasted message, a page or a tap. A case is one turn:
  "typed": what he typed ("" when a card's button sent it), "reply": Odie's reply,
  "made": the reminders the turn made ([{"title", "due_at"}]; also open tasks of his),
  "script": {"odie": […], "you": […]}: what the scripted model in the tests answers (the real model never sees it),
  "expect": {"promises": 1, "offers": 0, "promise_due": "2026-11-19T21", "offer_due": "2026-11-20"} (due: a prefix).
The read has no tools at all, so a case can't reach any mail, calendar or file. run_case takes the model call as an
argument: the tests pass the scripted one, odie/promises_eval.py the real model (scripts/promises_eval.sh)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from odie.loops import chat_read, ledger, offers

REPO = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO / "evals" / "promises"
CASES_DIR = EVAL_DIR / "cases"
SESSION = "chat-2026-11-19"


def load_cases() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]


def scripted(case: dict):
    """The tests' model: answers with the case's script."""
    async def think(prompt: str, instruction: str) -> str:
        return json.dumps(case.get("script") or {"odie": [], "you": []})
    return think


def score(case: dict, got: dict, gate: bool) -> dict:
    """Right and wrong for one case: each expected count, and each expected due day (a prefix of the kept time)."""
    expect = case["expect"]
    checks: list[tuple[str, bool]] = []
    checks.append(("promises", len(got["promises"]) == expect.get("promises", 0)))
    checks.append(("offers", len(got["offers"]) == expect.get("offers", 0)))
    if expect.get("promise_due"):
        dues = [d or "" for d in got["promise_dues"]]
        checks.append(("promise_due", any(d.startswith(expect["promise_due"]) for d in dues)))
    if expect.get("offer_due"):
        dues = [d or "" for d in got["offer_dues"]]
        checks.append(("offer_due", any(d.startswith(expect["offer_due"]) for d in dues)))
    wanted = expect.get("promises", 0) + expect.get("offers", 0)
    if wanted:
        checks.append(("gate", gate))
    wrong = [name for name, ok in checks if not ok]
    return {"right": len(checks) - len(wrong), "of": len(checks), "wrong": wrong}


async def run_case(store, case: dict, now: datetime, think) -> dict:
    """One case on a fresh store: its reminders made, the gate, the read; what came of it and its score."""
    made = case.get("made") or []
    for m in made:
        store.add_task(m["title"], "reminder", due_at=m.get("due_at"), origin="agent")
    gate = chat_read.worth_reading(case["typed"], case["reply"])
    got = {"promises": [], "offers": []}
    if gate:
        got = await chat_read.read(store, SESSION, now, case["typed"], case["reply"], think, made)
    promise_loops = [ledger.get(store, lid) for lid in got["promises"]]
    offered = [offers.get(store, "", oid) for oid in got["offers"]]
    out = {"promises": got["promises"], "offers": got["offers"],
           "promise_titles": [lp["title"] for lp in promise_loops],
           "promise_dues": [lp["due_at"] for lp in promise_loops],
           "offer_titles": [o["what"] for o in offered], "offer_dues": [o["due"] for o in offered]}
    return {"id": case["id"], "gate": gate, "got": out, "score": score(case, out, gate)}


def totals(results: list[dict]) -> dict:
    right = sum(r["score"]["right"] for r in results)
    of = sum(r["score"]["of"] for r in results)
    return {"right": right, "of": of, "cases": len(results),
            "cases_right": sum(1 for r in results if not r["score"]["wrong"])}
