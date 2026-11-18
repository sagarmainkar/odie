"""How well Odie keeps loops (proactive design §3, "drift when a prompt or model changes"): made-up, messy cases
(`evals/loops/cases/*.json`) through the watch's turn and stage 4, scored for loop count, closes with evidence, and
cards. Each case is its mails, what GitHub says (a fake gh answers from it) and what should come of it:
  {"loops": 1}                    one loop for the whole case (fourteen mails about one pull request)
  {"closed": ["example/app#50"]}  that loop closed, with a reason
  {"cards": [...]}, {"no_card": [...]}  which loops end as a card on Pulse, and which never do
  {"tested_cards": [...]}         those end as a tested card with [Merge] (Odie ran their tests)
  {"untested": [...]}             no test ran for those (someone else's, a lockfile, no approved command)
  {"recipe_cards": ["you-dev/app"]}  a "Use this" card asks for that repo's test command
A case may start with loops already there ("open_loops": [{title, kind, refs, done}]), with test commands he approved
("recipes": {"you-dev/app": "make test"}), and with a throwaway repo standing in for GitHub's ("origin": {"repo":
"you-dev/app", "pulls": {"70": "echo '12 passed'"}}: each pull request's head is a commit whose test.sh, run by
`make test`, runs that).

run_case takes the turn and the model call as arguments: tests pass scripted ones (deterministic, so the code's part
is held to the score), and odie/loops_eval.py passes the real model (scripts/loops_eval.sh)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from odie.loops import cards, clock, ledger, pr_test, recipes, shortcut

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


GIT = ["git", "-c", "user.name=Eval", "-c", "user.email=eval@example.com", "-c", "commit.gpgsign=false",
       "-c", "init.defaultBranch=main"]
TEST_WAIT = 120  # seconds a case waits for Odie's tests to finish


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def build_origin(case: dict, folder: Path) -> None:
    """A throwaway local repo for the case's "origin" (never a clone from the network): main, and each pull request's
    head commit at refs/pull/<n>/head with a test.sh that runs its line. The case's gh data learns each head's sha
    and where to clone from."""
    origin = case.get("origin")
    if not origin:
        return
    repo = folder / "origin"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("A made-up app.\n")
    (repo / "Makefile").write_text("test:\n\tsh test.sh\n")  # the approved command is `make test`
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    gh = case.setdefault("gh", {})
    for number, line in origin["pulls"].items():
        _git(repo, "checkout", "-q", "-B", f"pr-{number}", "main")
        (repo / "test.sh").write_text(f"#!/bin/sh\n{line}\n")
        (repo / f"change_{number}.py").write_text("print(1)\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"pull request {number}")
        sha = _git(repo, "rev-parse", "HEAD")
        _git(repo, "update-ref", f"refs/pull/{number}/head", sha)
        gh[f"pr:{origin['repo']}#{number}"]["headRefOid"] = sha
        for commit in gh[f"pr:{origin['repo']}#{number}"].get("commits") or []:
            commit["oid"] = sha
    _git(repo, "checkout", "-q", "main")
    gh[f"clone:{origin['repo']}"] = str(repo)


async def tests_done(store) -> None:
    """Waits (up to TEST_WAIT) until no test Odie started is queued or running."""
    for _ in range(TEST_WAIT * 10):
        if store.one("select 1 from jobs where kind='pr_test' and status in ('queued','running')") is None:
            return
        await asyncio.sleep(0.1)


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
    for ref in expect.get("tested_cards", []):
        checks += 1
        loop = loop_of_ref(store, ref)
        tested = None
        if loop is not None:
            tested = pr_test.result_for(store, loop["id"])
        if loop is None or loop["state"] != "ready" or cards.card(loop, tested)["main"]["action"] != "merge":
            wrong.append(f"{ref} has no tested card with Merge")
    for ref in expect.get("untested", []):
        checks += 1
        loop = loop_of_ref(store, ref)
        if loop is not None and store.one("select 1 from jobs where kind='pr_test' and loop_id=?", (loop["id"],)):
            wrong.append(f"{ref} was tested and shouldn't be")
    for repo in expect.get("recipe_cards", []):
        checks += 1
        if recipes.offered(store, repo) is None:
            wrong.append(f"no Use this card for {repo}")
    return {"right": checks - len(wrong), "of": checks, "wrong": wrong, "loops": count}


def seed_loops(store, case: dict, now: datetime) -> None:
    """The loops a case starts with ("open_loops"): each open and due, or closed by the user's Done ("done": true)."""
    from datetime import timedelta
    for seed in case.get("open_loops", []):
        lid = ledger.open_loop(store, "", now - timedelta(hours=6), seed["title"], seed["kind"], refs=seed["refs"],
                               playbook="github-pr", fact="seen before")
        if seed.get("done"):
            ledger.done(store, lid, now - timedelta(hours=5))


async def run_case(store, case: dict, now: datetime, turn, think, folder: Path) -> dict:
    """One case end to end: its mails through the watch's turn (stages 1 and 2), then stage 4 for every loop that is
    due, then the score. turn(prompt, tools, instruction) and think(prompt, instruction) are the model's."""
    from odie.watch import check as watch_check
    from odie.watch.eval import EvalFetcher
    from odie.watch.tools import Check, watch_tools
    from odie.workers import router
    case = json.loads(json.dumps(case))  # its gh data gains the origin's commits: this run's copy only
    build_origin(case, folder)
    use_fake_gh(case, folder)
    store.execute("delete from loop_events")
    store.execute("delete from loops")
    store.execute("delete from jobs")
    store.execute("delete from settings where key like 'loops.%'")
    for repo, command in (case.get("recipes") or {}).items():
        recipes.approve(store, repo, command, now)
    if router.hooks.get("store") is not store:
        router.setup(store, router.hooks.get("runner"))
    seed_loops(store, case, now)
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
    if any(got == "test" for _, got in ran):  # Odie is testing: wait for the tests, then stage 4 reads them
        await tests_done(store)
        ran += await clock.run(store, now, lambda pid: think, None, most=50)
    return {"id": case["id"], "error": error, "ran": ran, "score": score(case, store)}


def totals(results: list[dict]) -> dict:
    out = {"right": 0, "of": 0, "wrong": []}
    for r in results:
        out["right"] += r["score"]["right"]
        out["of"] += r["score"]["of"]
        out["wrong"] += [f"{r['id']}: {w}" for w in r["score"]["wrong"]]
    return out
