"""How well the evening review judges (phase 5): made-up ledgers (`evals/review/cases/*.json`) through the real review
(odie.loops.review.run: prompt, one call, rails, digest), scored for the merges it should and shouldn't make, the
loops it marks stale, the priority it sets, and nothing done for a loop's mail-born words. A case:
  "loops": [{"key", "title", "kind", "owner", "state", "days_ago", "due", "card", "evidence": [{"source", "fact",
            "days_ago"}]}],
  "tomorrow": [{"title", "start"}] (the watch card's saved events), "now_list": [...],
  "script": the scripted model's answer, with loop keys for numbers (the real model never sees it),
  "expect": {"merged": [[a, b]], "not_merged": [[a, b]], "stale": [a], "untouched": [a], "priority": {a: "high"},
             "not_high": [a]}
The review has no tools at all, so a case can't reach any mail, calendar or file. run_case takes the model call as
an argument: the tests pass the scripted one, odie/review_eval.py the real model (scripts/review_eval.sh)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from odie.loops import ledger, review
from odie.loops import now as now_list

REPO = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO / "evals" / "review"
CASES_DIR = EVAL_DIR / "cases"


def load_cases() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]


def setup(store, case: dict, now: datetime) -> dict[str, int]:
    """The case's ledger, events and Now list on a fresh store. Returns loop key -> id."""
    ids = {}
    for spec in case["loops"]:
        at = now - timedelta(days=spec.get("days_ago", 1))
        owner = spec.get("owner", "you")
        state = spec.get("state") or ("ready" if owner == "you" else "waiting")
        lid = ledger.open_loop(store, "", at, spec["title"], spec.get("kind", ""), owner=owner, state=state,
                               due_at=spec.get("due"), card=spec.get("card"))
        for e in spec.get("evidence") or []:
            when = now - timedelta(days=e.get("days_ago", spec.get("days_ago", 1)))
            ledger.add_event(store, lid, when, e.get("source", "mail"), e.get("ref", ""), e["fact"])
        ids[spec["key"]] = lid
    store.set_setting("watch.card", {"events": case.get("tomorrow") or []})
    if case.get("now_list"):
        now_list.save(store, "", case["now_list"], now)
    return ids


def with_ids(value, ids: dict[str, int]):
    """The script with loop keys turned into the loop numbers of this run: {"loops": ["deck", "call"]} -> [3, 4]."""
    if isinstance(value, dict):
        return {k: with_ids(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [with_ids(v, ids) for v in value]
    if isinstance(value, str) and value in ids:
        return ids[value]
    return value


def scripted(case: dict, ids: dict[str, int]):
    """The tests' model: answers with the case's script."""
    async def think(prompt: str, instruction: str) -> str:
        return json.dumps(with_ids(case.get("script") or {}, ids))
    return think


def merged_pair(store, a: int, b: int) -> bool:
    """Whether one of two loops was merged into the other."""
    for one, other in ((a, b), (b, a)):
        loop = ledger.get(store, one)
        if loop is not None and loop["card"].get("merged_into") == other:
            return True
    return False


def touched(store, lid: int) -> bool:
    """Whether the review closed, merged or marked a loop (a priority change alone doesn't count)."""
    loop = ledger.get(store, lid)
    if loop is None or loop["state"] not in ledger.OPEN:
        return True
    if loop["card"].get("stale") or loop["card"].get("split_from"):
        return True
    return any(e["fact"].startswith("Evening review: merged") for e in ledger.events(store, lid))


def is_stale(store, lid: int) -> bool:
    loop = ledger.get(store, lid)
    return bool(loop["card"].get("stale")) or (loop["state"] == "dropped" and loop["closed_by"] == "odie")


def score(store, case: dict, ids: dict[str, int]) -> dict:
    expect = case["expect"]
    checks: list[tuple[str, bool]] = []
    for a, b in expect.get("merged") or []:
        checks.append((f"merged {a}+{b}", merged_pair(store, ids[a], ids[b])))
    for a, b in expect.get("not_merged") or []:
        checks.append((f"not merged {a}+{b}", not merged_pair(store, ids[a], ids[b])))
    for a in expect.get("stale") or []:
        checks.append((f"stale {a}", is_stale(store, ids[a])))
    for a in expect.get("untouched") or []:
        checks.append((f"untouched {a}", not touched(store, ids[a])))
    for a, level in (expect.get("priority") or {}).items():
        checks.append((f"priority {a} {level}", ledger.get(store, ids[a])["priority"] == level))
    for a in expect.get("not_high") or []:
        checks.append((f"not high {a}", ledger.get(store, ids[a])["priority"] != "high"))
    wrong = [name for name, ok in checks if not ok]
    return {"right": len(checks) - len(wrong), "of": len(checks), "wrong": wrong}


async def run_case(store, case: dict, now: datetime, think=None) -> dict:
    """One case on a fresh store: the ledger set up, the review run, what came of it and its score. think: the model
    call (None: the case's script)."""
    ids = setup(store, case, now)
    if think is None:
        think = scripted(case, ids)
    got = await review.run(store, "", now, think)
    from odie.loops import digest
    return {"id": case["id"], "changes": [c["words"] for c in got["changes"]], "refused": got["refused"],
            "digest": (digest.evening(store, "") or {}).get("text", ""), "score": score(store, case, ids)}


def totals(results: list[dict]) -> dict:
    right = sum(r["score"]["right"] for r in results)
    of = sum(r["score"]["of"] for r in results)
    return {"right": right, "of": of, "cases": len(results),
            "cases_right": sum(1 for r in results if not r["score"]["wrong"])}
