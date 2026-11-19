"""Stage 4, Choose (proactive design §7), for loops with the github-pr playbook. For one due loop: the facts from
GitHub (step pr_facts or issue_facts, tier 0: code builds the gh command from the loop's checked ref), then one call to
the model with no tools, the facts fenced as other people's text, which picks:
  drop  -> the loop closes, citing the facts' evidence when there is some ("merged 18 Nov 21:04"), else its reason
  wait  -> next check in 1 to 24 hours
  ready -> a card on Pulse: the facts line and the link written by code, the model's brief; a push when it is high
           priority (within the shared push budget)
  test  -> step test_pr (tier 1), if the rail allows (odie.loops.rail): code runs the tests in one of Odie's own
           Worker slots (odie.loops.pr_test) and the loop waits for them. Refused -> a ready card from GitHub's CI
           facts, the reason in its evidence; no approved command yet -> a "Use this" card for his tap first.
Once the head commit is tested, the next call reads the test's output and the diff (capped), fenced, and writes the
brief and a draft review (never posted); the card then reads "Tested: 412 pass · CI green · 3 files, +41 −9" with
[Merge], or "2 tests fail" with [Show failures]. New commits after a test: the model sees the test is of an older
commit and may test again; the same loop, so the same card, never a second.
A muddle (no facts, no clear choice, a drop with no reason) waits an hour; the second in a row becomes an
"I'm stuck" card, so a loop never silently spins."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from odie.agent.callbacks import wrap_untrusted
from odie.loops import budget, github, ledger, playbooks, pr_test, rail, recipes

log = logging.getLogger("odie.loops")
CHOICES = ("drop", "wait", "ready", "test")
STUCK_AFTER = 2  # muddles in a row before the loop becomes an "I'm stuck" card
READY_RECHECK = timedelta(hours=6)  # a card still on Pulse is looked at again, so a PR merged meanwhile closes itself
BRIEF_MOST = 600
REVIEW_MOST = 1500
TEST_RECHECK = timedelta(minutes=50)  # a loop whose test runs is looked at again after the test's budget at most
ASK_RECHECK = timedelta(hours=24)  # a loop waiting for his OK on a test command
EVIDENCE_LINES = 8


def first_ref(loop: dict) -> github.Ref | None:
    """The loop's GitHub name to look up: the first of its refs that checks out. ["thread:t9", "example/app#49"] ->
    example/app#49; only a thread -> None."""
    for ref in loop["refs"]:
        parsed = github.parse(ref)
        if parsed is not None:
            return parsed
    return None


def is_issue(loop: dict) -> bool:
    """Whether the loop is an issue (step issue_facts) rather than a pull request: kind "issue" -> True; "pull
    request" -> False."""
    return "issue" in (loop["kind"] or "").lower()


def parse_choice(text: str) -> dict | None:
    """The model's answer as {choice, why, hours, brief}, from the first JSON object in its reply; None when there is
    no such object or its choice isn't one of drop, wait, ready. Hours are kept within 1 to 24.
      'Sure. {"choice": "wait", "why": "draft", "hours": 30}' -> {"choice": "wait", "why": "draft", "hours": 24, …}
      "no idea" -> None;  '{"choice": "merge"}' -> None"""
    found = re.search(r"\{.*\}", text or "", re.S)
    if found is None:
        return None
    try:
        raw = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict) or raw.get("choice") not in CHOICES:
        return None
    try:
        hours = int(raw.get("hours") or 1)
    except (TypeError, ValueError):
        hours = 1
    hours = max(1, min(24, hours))
    return {"choice": raw["choice"], "why": str(raw.get("why") or "").strip()[:200], "hours": hours,
            "brief": str(raw.get("brief") or "").strip()[:BRIEF_MOST],
            "review": str(raw.get("review") or "").strip()[:REVIEW_MOST]}


def prompt_for(loop: dict, evidence: list[dict], facts: dict, tested: dict | None = None, older: dict | None = None,
               diff: str = "", now_text: str = "") -> str:
    """What the model reads: the loop in one line, its recent evidence and the fresh facts, each fenced (the title
    and the evidence carry mail subjects, the facts GitHub titles: other people's words). With a test of the head
    commit: its result and output's tail, and the diff, fenced too. With a test of an older commit: a line saying so.
    now_text: his Now list (odie.loops.now), his own words, so the model can judge what is worth his attention."""
    said = "\n".join(f"- {e['at'][:16]} {e['source']}: {e['fact']}" for e in evidence[-EVIDENCE_LINES:])
    shown = {k: v for k, v in facts.items() if k != "paths"}
    shown["files_changed"] = (facts.get("paths") or [])[:40]
    text = (f"Loop:\n{wrap_untrusted(ledger.line(loop, evidence))}\n\nEvidence so far:\n{wrap_untrusted(said or '(none)')}\n\n"
            f"Facts from GitHub just now:\n{wrap_untrusted(json.dumps(shown, ensure_ascii=False))}\n\n")
    if now_text:
        text += f"What matters to the user now (his Now list):\n{now_text}\n\n"
    if tested is not None:
        result = {k: tested.get(k) for k in ("command", "exit", "passed", "failed", "ok", "error")}
        text += (f"Odie tested the head commit {tested['sha'][:7]} (code ran it; these are facts):\n"
                 f"{wrap_untrusted(json.dumps(result, ensure_ascii=False))}\nThe output's tail:\n"
                 f"{wrap_untrusted(tested.get('tail') or '(none)')}\n\nThe diff:\n{wrap_untrusted(diff or '(none)')}\n\n"
                 "Write the brief and a draft review (it is not posted). Choose drop, wait or ready.")
        return text
    if older is not None:
        text += (f"Your last test was of an older commit ({older['sha'][:7]}); there are new commits since, untested.\n\n")
    return text + "Choose drop, wait, ready or test."


async def facts_for(loop: dict, ref: github.Ref, book: playbooks.Playbook) -> dict:
    """The step's facts. The step must be one the playbook declares at tier 0 (read-only); any other is refused."""
    step = "pr_facts"
    if is_issue(loop):
        step = "issue_facts"
    if book.steps.get(step) != 0:
        raise github.GitHubError(f"{book.name} doesn't declare {step} as a read")
    if step == "issue_facts":
        return await github.issue_facts(ref)
    return await github.pr_facts(ref)


def muddle(store, loop: dict, now: datetime, reason: str, link: str = "") -> str:
    """No clear way forward this time: wait an hour, and on the STUCK_AFTER-th in a row show an "I'm stuck" card
    instead. 1st -> "wait"; 2nd -> "stuck" (a card: "I'm stuck on this one", why in the brief)."""
    attempts = int(loop["attempts"]) + 1
    log.info("loop #%s: %s (attempt %d)", loop["id"], reason, attempts)
    if attempts >= STUCK_AFTER:
        ledger.update(store, loop["id"], now, state="ready", attempts=attempts, has_news=0,
                      result="I'm stuck on this one", brief=reason[:BRIEF_MOST], link=link,
                      next_check_at=(now + READY_RECHECK).isoformat(timespec="seconds"))
        return "stuck"
    ledger.update(store, loop["id"], now, state="waiting", attempts=attempts, has_news=0,
                  next_check_at=(now + timedelta(hours=1)).isoformat(timespec="seconds"))
    return "wait"


async def choose(store, loop: dict, now: datetime, think, push=None) -> str:
    """Stage 4 for one due loop (this module's notes). think(prompt, instruction) is the model call, with no tools,
    on the loop's owner's brain. push(title, body) sends a push. Returns what happened: "drop", "wait", "ready",
    "test", "ask", "stuck", "skip" (no playbook) or "over budget" (no call left today: the loop stays due)."""
    book = playbooks.get(loop["playbook"])
    if book is None:
        ledger.update(store, loop["id"], now, has_news=0, next_check_at=None)
        return "skip"
    ref = first_ref(loop)
    if ref is None:
        return muddle(store, loop, now, "It has no GitHub name I can look up.")
    link = github.link(ref, loop["kind"])
    if pr_test.running_for(store, loop["id"]):
        ledger.update(store, loop["id"], now, has_news=0, next_check_at=(now + TEST_RECHECK).isoformat(timespec="seconds"))
        return "wait"  # its test is running: nothing to decide until it ends
    try:
        facts = await facts_for(loop, ref, book)
    except (github.GitHubError, ValueError) as e:
        return muddle(store, loop, now, f"GitHub didn't answer: {e}", link)
    headline = github.headline(facts)
    ledger.add_event(store, loop["id"], now, "gh", str(ref), headline)
    tested, older = tests_of(store, loop, facts)
    diff = ""
    if tested is not None:
        diff = await diff_for(ref)
    if not budget.spend(store, now):
        return "over budget"
    try:
        from odie.loops import now as now_list
        prompt = prompt_for(loop, ledger.events(store, loop["id"]), facts, tested, older, diff,
                            now_list.text(store, loop["personality"]))
        answer = await think(prompt, book.text)
    except Exception as e:  # noqa: BLE001 (a failed call is a muddle, never a crash of the clock)
        return muddle(store, loop, now, f"The model didn't answer: {type(e).__name__}", link)
    picked = parse_choice(answer)
    if picked is None:
        return muddle(store, loop, now, "I couldn't decide what to do with it.", link)
    if picked["choice"] == "drop":
        return drop(store, loop, now, facts, picked, link)
    if picked["choice"] == "test" and tested is None:
        return await test_step(store, loop, now, ref, facts, picked, link, push)
    if picked["choice"] == "wait":
        ledger.update(store, loop["id"], now, state="waiting", attempts=0, has_news=0, next_step=picked["why"],
                      next_check_at=(now + timedelta(hours=picked["hours"])).isoformat(timespec="seconds"))
        return "wait"
    return ready(store, loop, now, facts, picked, link, push, tested)


def ready(store, loop: dict, now: datetime, facts: dict, picked: dict, link: str, push, tested: dict | None) -> str:
    """The loop becomes a card. Its facts line is code's: from the test of the head commit when there is one
    ("Tested: 412 pass · CI green · 3 files, +41 −9"; Merge may then be offered, odie.loops.cards), else from GitHub's
    facts ("Open · CI green · 3 files, +41 −9"). A draft review is kept as evidence (Why?), never posted."""
    from odie.watch import pushes
    headline = github.headline(facts)
    if tested is not None:
        headline = tested_headline(tested, facts)
        pr_test.mark_carded(store, loop["id"], facts.get("checks", "none"), card_title(facts))
        if picked["review"]:
            ledger.add_event(store, loop["id"], now, "review", "draft", f"Draft review (not posted): {picked['review']}")
    was_ready = loop["state"] == "ready"
    ledger.update(store, loop["id"], now, state="ready", attempts=0, has_news=0, result=headline,
                  brief=picked["brief"], link=link, next_step=picked["why"],
                  next_check_at=(now + READY_RECHECK).isoformat(timespec="seconds"))
    if not was_ready:
        ledger.update(store, loop["id"], now, shown_at=now.isoformat(timespec="seconds"))
    if push is not None and not was_ready and loop["priority"] == "high":
        pushes.started_by_odie(store, now, loop["personality"], loop["title"], headline, push, ref=f"loop:{loop['id']}")
    return "ready"


def card_title(facts: dict) -> str:
    """A tested card's title, written by code: "example/app #49 · Threads newest first"."""
    ref = github.parse(facts.get("ref", ""))
    if ref is None:
        return facts.get("title", "")
    return f"{ref.repo_path} #{ref.number} · {facts.get('title', '')}"


def tested_headline(tested: dict, facts: dict) -> str:
    """The tested card's facts line, written by code from the test's record and GitHub's facts:
      exit 0, 412 passed       -> "Tested: 412 pass · CI green · 3 files, +41 −9"
      exit 0, no counts        -> "Tested: tests pass · CI green · …"
      exit 1, 2 failed         -> "2 tests fail · CI green · …";  1 failed -> "1 test fails · …"
      exit 2, no counts        -> "Tests fail (exit 2) · …";  over time -> "Tests timed out · …"
      couldn't run             -> "The test couldn't run · …" """
    size = github.size_words(facts.get("files", 0), facts.get("additions", 0), facts.get("deletions", 0))
    ci = github.ci_words(facts)
    if tested.get("error"):
        first = "The test couldn't run"
    elif tested.get("exit") is None:
        first = "Tests timed out"
    elif tested.get("ok"):
        first = "Tested: tests pass"
        if tested.get("passed") is not None:
            first = f"Tested: {tested['passed']} pass"
    elif tested.get("failed"):
        first = f"{tested['failed']} tests fail"
        if tested["failed"] == 1:
            first = "1 test fails"
    else:
        first = f"Tests fail (exit {tested['exit']})"
    return f"{first} · {ci} · {size}"


def tests_of(store, loop: dict, facts: dict) -> tuple[dict | None, dict | None]:
    """The loop's last test, sorted against the head commit now: (the test of this head, None), or (None, the test of
    an older commit), or (None, None) when it was never tested or its test couldn't run (cut off by a restart, a
    failed clone), so it may be tested again (Odie's 8 a day bound that). A test of an older commit loses its Merge.
      tested abc…, head abc… -> (that test, None);  tested abc…, head def… -> (None, that test);
      never, or abc…'s test cut off by a restart -> (None, None)"""
    result = pr_test.result_for(store, loop["id"])
    if result is None or result.get("error"):
        return None, None
    if facts.get("head_sha") and result.get("sha") == facts["head_sha"]:
        return result, None
    if result.get("carded"):
        pr_test.uncard(store, loop["id"])
    return None, result


async def diff_for(ref: github.Ref) -> str:
    try:
        return await github.pr_diff(ref)
    except github.GitHubError as e:
        return f"(the diff couldn't be read: {e})"


async def test_step(store, loop: dict, now: datetime, ref: github.Ref, facts: dict, picked: dict, link: str,
                    push) -> str:
    """The model asked for test_pr; the rail decides (odie.loops.rail). Returns:
      "test"  -> allowed: the test runs in one of Odie's own slots; the loop waits for it ("working")
      "ask"   -> all fine but no approved command: code proposes one, a "Use this" card waits for his tap
      "ready" -> refused (someone else's, a fork, the lockfile, he said no, 8 tests today): a card from CI facts,
                 with "Not tested: <why>" in its evidence"""
    repo = ref.repo_path
    recipe = recipes.approved(store, repo)
    facts = {**facts, "pushers": await github.pushers(ref), "write_keys": await github.write_keys(ref)}  # read now
    if store.get_setting(rail.SIGNED_ONLY):
        facts["signed_only"] = True
        facts["unsigned"] = await github.unsigned_commits(ref, facts.get("you", ""))
    why = rail.why_not(facts, recipe)
    if why == rail.NO_RECIPE:
        why = await offer_recipe(store, loop, now, ref)
        if why is None:
            return "ask"
    if why is None:
        sha = facts["head_sha"]
        job = pr_test.start(store, loop, ref, sha, recipe)
        if job is not None:
            ledger.add_event(store, loop["id"], now, "odie", sha[:7], f"Testing {sha[:7]} with `{recipe}`")
            ledger.update(store, loop["id"], now, state="working", attempts=0, has_news=0, next_step=f"testing {sha[:7]}",
                          next_check_at=(now + TEST_RECHECK).isoformat(timespec="seconds"))
            return "test"
        why = "today's tests by Odie are used up"
    ledger.add_event(store, loop["id"], now, "odie", "", f"Not tested: {why}")
    return ready(store, loop, now, facts, picked, link, push, None)


async def offer_recipe(store, loop: dict, now: datetime, ref: github.Ref) -> str | None:
    """No command approved for the repo yet: None after offering one (or when one is already offered), with the loop
    waiting for his tap; else why it can't be tested (he said no before; code knows no command for this repo)."""
    repo = ref.repo_path
    if recipes.declined(store, repo):
        return "you said no to testing this repo"
    if recipes.offered(store, repo) is None:
        try:
            names = await github.root_files(ref)
        except github.GitHubError:
            names = []
        command = recipes.suggest(names)
        if command is None:
            return f"I don't know how to test {repo}"
        recipes.offer(store, repo, command, loop, now)
        ledger.add_event(store, loop["id"], now, "odie", "", f"Asked you to approve `{command}` for {repo}")
    ledger.update(store, loop["id"], now, state="waiting", attempts=0, has_news=0,
                  next_step="waiting for your OK to test it",
                  next_check_at=(now + ASK_RECHECK).isoformat(timespec="seconds"))
    return None


def drop(store, loop: dict, now: datetime, facts: dict, picked: dict, link: str) -> str:
    """Closes the loop. With evidence in the facts (merged, closed) it is "closed" citing it; otherwise "dropped" with
    the model's reason; with neither, it is a muddle (a close must say why)."""
    evidence = github.evidence(facts)
    if evidence:
        ledger.close(store, loop["id"], now, "odie", evidence)
        return "drop"
    if not picked["why"]:
        return muddle(store, loop, now, "It wanted to drop it but didn't say why.", link)
    ledger.close(store, loop["id"], now, "odie", picked["why"], state="dropped")
    return "drop"
