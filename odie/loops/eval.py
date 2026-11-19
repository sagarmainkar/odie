"""How well Odie keeps loops (proactive design §3, "drift when a prompt or model changes"): made-up, messy cases
(`evals/loops/cases/*.json`) through the whole pipeline — stage 1 (the watch's turn), stage 2 (consolidate) and stage 4
for pull requests — scored for loop count, owner, due dates, reminders, closes with evidence, and cards. A case is one
check (its "mails", "events" and "sent") or several in order ("checks": [{"at", "mails", "events", "sent", "then":
{"done": [ref]}}]: "then" is what the user tapped after that check), what GitHub says (a fake gh answers from it), an
optional "watch_for", "memory" and "owner": "personality" (run as a personality's own watch), and what should come of it:
  {"loops": 1}                    one loop for the whole case (fourteen mails about one pull request)
  {"closed": ["example/app#50"]}  that loop closed, with a reason
  {"cards": [...]}, {"no_card": [...]}  which loops end as a card on Pulse, and which never do
  {"tested_cards": [...]}         those end as a tested card with [Merge] (Odie ran their tests)
  {"untested": [...]}             no test ran for those (someone else's, a lockfile, no approved command)
  {"recipe_cards": ["you-dev/app"]}  a "Use this" card asks for that repo's test command
  {"owner": {"mail:r1": "you"}}   the loop holding that ref is whose move it says
  {"due": {"mail:d1": "2026-11-20T15:00"}}  its due date starts so
  {"reminders": 1}                how many reminders Odie made (one per thing, whatever brought it back)
  {"why": true}                   every card has its evidence (Why?)
  {"odie_loops": 0}               (a personality's case) none of everyday Odie's
Each check may carry a "script" ({"findings": […], "answers": […]}): what the scripted model in the tests writes in
stage 1 and answers in stage 2. The real model never sees it.
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

from odie.loops import cards, clock, consolidate, findings, ledger, pr_test, recipes, shortcut

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


def score(case: dict, store, pid: str = "") -> dict:
    """One case's result against what it expects (this module's notes): each expectation right or wrong, and what
    went wrong in words. 14 loops where 1 was wanted -> loops wrong ("14 loops, wanted 1"); #50 still open where it
    should close -> "example/app#50 not closed"."""
    expect = case.get("expect") or {}
    count = store.one("select count(*) n from loops where coalesce(personality, '') = ?", (pid,))["n"]
    checks, wrong = 0, []
    if "loops" in expect:
        checks += 1
        if count != expect["loops"]:
            wrong.append(f"{count} loops, wanted {expect['loops']}")
    if "odie_loops" in expect:
        checks += 1
        odies = store.one("select count(*) n from loops where personality is null")["n"]
        if odies != expect["odie_loops"]:
            wrong.append(f"{odies} of everyday Odie's loops, wanted {expect['odie_loops']}")
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
    for ref, owner in (expect.get("owner") or {}).items():
        checks += 1
        loop = loop_of_ref(store, ref)
        if loop is None or loop["owner"] != owner:
            got = "no loop" if loop is None else loop["owner"]
            wrong.append(f"{ref} owner {got}, wanted {owner}")
    for ref, due in (expect.get("due") or {}).items():
        checks += 1
        loop = loop_of_ref(store, ref)
        if loop is None or not (loop["due_at"] or "").startswith(due):
            got = "no loop" if loop is None else loop["due_at"]
            wrong.append(f"{ref} due {got}, wanted {due}")
    if "reminders" in expect:
        checks += 1
        made = store.one("select count(*) n from tasks where source_kind = 'loop'")["n"]
        if made != expect["reminders"]:
            wrong.append(f"{made} reminders, wanted {expect['reminders']}")
    if expect.get("why"):
        checks += 1
        bare = [lp["title"] for lp in ledger.open_loops(store, pid) if lp["state"] == "ready"
                and not cards.why_lines(ledger.events(store, lp["id"]))]
        if bare:
            wrong.append(f"cards with no Why?: {', '.join(bare)}")
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


def seed_loops(store, case: dict, now: datetime, pid: str = "") -> None:
    """The loops a case starts with ("open_loops"): each open and due, or closed by the user's Done ("done": true).
    A pull request gets its playbook; anything else is his card ("owner": "you") or followed."""
    from datetime import timedelta
    for seed in case.get("open_loops", []):
        playbook = ""
        if "pull request" in seed["kind"] or "issue" in seed["kind"]:
            playbook = "github-pr"
        owner = seed.get("owner", "odie")
        state = consolidate.state_for(owner, playbook)
        lid = ledger.open_loop(store, pid, now - timedelta(hours=6), seed["title"], seed["kind"], owner=owner,
                               refs=seed["refs"], playbook=playbook, fact=seed.get("fact", "seen before"), state=state,
                               card=seed.get("card"))
        if seed.get("done"):
            ledger.done(store, lid, now - timedelta(hours=5))


def checks_of(case: dict) -> list[dict]:
    """A case's checks in order: its "checks", or one made of its top-level mails, events and sent mail."""
    if case.get("checks"):
        return case["checks"]
    return [{"mails": case.get("mails", []), "events": case.get("events", []), "sent": case.get("sent", []),
             "script": case.get("script")}]


def taps(store, pid: str, now: datetime, then: dict | None) -> None:
    """What the user tapped after a check: {"done": ["event:uid1"]} -> Done on the loop holding that ref."""
    for ref in (then or {}).get("done", []):
        loop = loop_of_ref(store, ref)
        if loop is not None and loop["state"] in ledger.OPEN:
            ledger.done(store, loop["id"], now)


async def one_check(store, case: dict, chk: dict, at: datetime, pid: str, turn, think) -> str:
    """One check of the case: code's reads (sent mail closes what it answers, the shortcut), stage 1 (with one nudge
    when it stops short, as live) and stage 2. Returns the turn's error, or ""."""
    from odie.watch import check as watch_check
    from odie.watch import sent
    from odie.watch.eval import EvalFetcher, calendar_fakes, mail_of
    from odie.watch.tools import Check, watch_tools
    fetcher = EvalFetcher(store, at, {**case, "mails": chk.get("mails", []), "events": chk.get("events", [])}, pid)
    check = Check(fetcher)
    mine = []
    for row in chk.get("sent", []):
        mail = mail_of(row)
        mail.to = row.get("to", "")
        mine.append(mail)
    check.sent = sent.close_answered(store, at, mine, pid)
    check.mails = await fetcher.new_mail()
    check.mail_read = True
    check.events = await fetcher.upcoming_events()
    check.loop_of = shortcut.attach_known(store, pid, check.mails, at)
    check.script = chk.get("script") or {}
    writes: list[dict] = []
    tools = watch_tools(check) + calendar_fakes(writes)
    instruction = watch_check._instruction(case.get("watch_for", ""))
    watch_check.STAGE1.reset(store, pid, case.get("watch_for", ""))  # what this check may reach, as live
    error = ""
    try:
        await turn(PROMPT, tools, instruction, check.script)
        if check.report is None:
            await turn(watch_check.nudge_text(check), tools, instruction, check.script)
    except Exception as e:  # noqa: BLE001 (a failed case is recorded; the rest still run)
        error = f"{type(e).__name__}: {e}"[:200]
    found = findings.collect(check)

    async def think_here(prompt, instruction):
        return await think(prompt, instruction, check.script)
    context = {"watch": case.get("watch_for", ""), "memory": case.get("memory", "")}
    await consolidate.consolidate(store, pid, at, found, think_here, context)
    return error


async def run_case(store, case: dict, now: datetime, turn, think, folder: Path) -> dict:
    """One case end to end: each check through stages 1 and 2, then stage 4 for every loop that is due, then the
    user's taps; at the end, the score. turn(prompt, tools, instruction, script) is stage 1's model turn;
    think(prompt, instruction, script) answers stage 2 and stage 4 (script: the check's, for a scripted model; the
    real model ignores it)."""
    from odie import personalities
    from odie.watch import owner as watch_owner
    from odie.workers import router
    case = json.loads(json.dumps(case))  # its gh data gains the origin's commits: this run's copy only
    build_origin(case, folder)
    use_fake_gh(case, folder)
    for table in ("loop_events", "loops", "jobs", "tasks"):
        store.execute(f"delete from {table}")
    store.execute("delete from settings where key like 'loops.%' or key like 'watch.%' or key like 'push.%'")
    for repo, command in (case.get("recipes") or {}).items():
        recipes.approve(store, repo, command, now)
    if router.hooks.get("store") is not store:
        router.setup(store, router.hooks.get("runner"))
    pid = ""
    if case.get("owner") == "personality":
        pid = personalities.create(store, "Mira").id
        watch_owner.set_proactive(store, pid, True)  # so the clock runs its loops
    seed_loops(store, case, now, pid)
    errors, ran = [], []

    async def think_plain(prompt, instruction):
        return await think(prompt, instruction, {})
    for chk in checks_of(case):
        at = now
        if chk.get("at"):
            at = datetime.fromisoformat(chk["at"])
        error = await one_check(store, case, chk, at, pid, turn, think)
        if error:
            errors.append(error)
        got = await clock.run(store, at, lambda _pid: think_plain, None, most=50)
        if any(what == "test" for _, what in got):  # Odie is testing: wait for the tests, then stage 4 reads them
            await tests_done(store)
            got += await clock.run(store, at, lambda _pid: think_plain, None, most=50)
        ran += got
        taps(store, pid, at, chk.get("then"))
    return {"id": case["id"], "error": "; ".join(errors), "ran": ran, "score": score(case, store, pid)}


def totals(results: list[dict]) -> dict:
    out = {"right": 0, "of": 0, "wrong": []}
    for r in results:
        out["right"] += r["score"]["right"]
        out["of"] += r["score"]["of"]
        out["wrong"] += [f"{r['id']}: {w}" for w in r["score"]["wrong"]]
    return out
