"""Stage 4, Choose (proactive design §7), for loops with the github-pr playbook (phase 1: read-only). For one due
loop: the facts from GitHub (step pr_facts or issue_facts, tier 0: code builds the gh command from the loop's checked
ref), then one call to the model with no tools, the facts fenced as other people's text, which picks:
  drop  -> the loop closes, citing the facts' evidence when there is some ("merged 18 Nov 21:04"), else its reason
  wait  -> next check in 1 to 24 hours
  ready -> a card on Pulse: the facts line and the link written by code, the model's brief; a push when it is high
           priority (within the shared push budget)
A muddle (no facts, no clear choice, a drop with no reason) waits an hour; the second in a row becomes an
"I'm stuck" card, so a loop never silently spins."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from odie.agent.callbacks import wrap_untrusted
from odie.loops import budget, github, ledger, playbooks

log = logging.getLogger("odie.loops")
CHOICES = ("drop", "wait", "ready")
STUCK_AFTER = 2  # muddles in a row before the loop becomes an "I'm stuck" card
READY_RECHECK = timedelta(hours=6)  # a card still on Pulse is looked at again, so a PR merged meanwhile closes itself
BRIEF_MOST = 600
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
            "brief": str(raw.get("brief") or "").strip()[:BRIEF_MOST]}


def prompt_for(loop: dict, evidence: list[dict], facts: dict) -> str:
    """What the model reads: the loop in one line, its recent evidence and the fresh facts, both fenced (mail subjects
    and GitHub titles are other people's words)."""
    said = "\n".join(f"- {e['at'][:16]} {e['source']}: {e['fact']}" for e in evidence[-EVIDENCE_LINES:])
    return (f"Loop: {ledger.line(loop, evidence)}\n\nEvidence so far:\n{wrap_untrusted(said or '(none)')}\n\n"
            f"Facts from GitHub just now:\n{wrap_untrusted(json.dumps(facts, ensure_ascii=False))}\n\n"
            "Choose drop, wait or ready.")


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
    "stuck", "skip" (no playbook) or "over budget" (no call left today: the loop stays due)."""
    from odie.watch import pushes
    book = playbooks.get(loop["playbook"])
    if book is None:
        ledger.update(store, loop["id"], now, has_news=0, next_check_at=None)
        return "skip"
    ref = first_ref(loop)
    if ref is None:
        return muddle(store, loop, now, "It has no GitHub name I can look up.")
    link = github.link(ref, loop["kind"])
    try:
        facts = await facts_for(loop, ref, book)
    except (github.GitHubError, ValueError) as e:
        return muddle(store, loop, now, f"GitHub didn't answer: {e}", link)
    headline = github.headline(facts)
    ledger.add_event(store, loop["id"], now, "gh", str(ref), headline)
    if not budget.spend(store, now):
        return "over budget"
    try:
        answer = await think(prompt_for(loop, ledger.events(store, loop["id"]), facts), book.text)
    except Exception as e:  # noqa: BLE001 (a failed call is a muddle, never a crash of the clock)
        return muddle(store, loop, now, f"The model didn't answer: {type(e).__name__}", link)
    picked = parse_choice(answer)
    if picked is None:
        return muddle(store, loop, now, "I couldn't decide what to do with it.", link)
    if picked["choice"] == "drop":
        return drop(store, loop, now, facts, picked, link)
    if picked["choice"] == "wait":
        ledger.update(store, loop["id"], now, state="waiting", attempts=0, has_news=0, next_step=picked["why"],
                      next_check_at=(now + timedelta(hours=picked["hours"])).isoformat(timespec="seconds"))
        return "wait"
    was_ready = loop["state"] == "ready"
    ledger.update(store, loop["id"], now, state="ready", attempts=0, has_news=0, result=headline,
                  brief=picked["brief"], link=link, next_step=picked["why"],
                  next_check_at=(now + READY_RECHECK).isoformat(timespec="seconds"))
    if not was_ready:
        ledger.update(store, loop["id"], now, shown_at=now.isoformat(timespec="seconds"))
    if push is not None and not was_ready and loop["priority"] == "high":
        pushes.started_by_odie(store, now, loop["personality"], loop["title"], headline, push)
    return "ready"


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
