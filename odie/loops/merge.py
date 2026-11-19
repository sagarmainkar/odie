"""[Merge] (proactive design §7 step 8, §16 Q2): one tap on a tested card is the approval. Only his tap in the app
reaches this (POST /api/loops/{id}/merge; the terminal's key can't, and no model has a tool for it). The command is
fixed and built by code, pinned to the commit that was tested:
    gh pr merge <n> --repo <owner/repo> --squash --match-head-commit <sha>
so GitHub refuses if anything was pushed after the test. Then gh is asked again, and only its word closes the loop
("merged 18 Nov 21:04", under Done today). New commits: the merge is refused and the loop tests again."""
from __future__ import annotations

from datetime import datetime

from odie.loops import cards, choose, github, ledger, pr_test


class MergeRefused(Exception):
    """Why the merge didn't happen, in words for the card."""


async def merge(store, loop_id: int, now: datetime) -> str:
    """Merges the loop's tested pull request and closes the loop; returns why it closed ("merged 18 Nov 21:04").
    Raises MergeRefused: no such open loop; no passing test carded for it; new commits since the test (the loop is
    then looked at again, to test the new head); GitHub refused or hasn't confirmed."""
    loop = ledger.get(store, loop_id)
    if loop is None or loop["state"] not in ledger.OPEN:
        raise MergeRefused("That card isn't there any more.")
    tested = pr_test.result_for(store, loop_id)
    if not cards.may_merge(tested):
        raise MergeRefused("Only a pull request Odie tested, with its tests passing, merges from here.")
    ref = choose.first_ref(loop)
    if ref is None:
        raise MergeRefused("It has no GitHub name I can merge.")
    sha = tested["sha"]
    try:
        now_facts = await github.pr_facts(ref)  # read again: the head and CI as they are at his tap
    except github.GitHubError as e:
        raise MergeRefused(f"GitHub didn't answer: {e}") from e
    if await moved_on(store, loop, ref, sha, now, now_facts):
        raise MergeRefused(f"There are new commits since the test of {sha[:7]}: not merged. I'll test them first.")
    if now_facts.get("checks") not in ("green", "none"):
        ledger.update(store, loop_id, now, has_news=1)
        raise MergeRefused(f"GitHub's CI is {github.ci_words(now_facts).lower()} now: not merged.")
    try:
        await github.merge(ref, sha)
    except (github.GitHubError, ValueError) as e:
        if await moved_on(store, loop, ref, sha, now):
            raise MergeRefused(f"There are new commits since the test of {sha[:7]}: not merged. I'll test them first.") from e
        raise MergeRefused(f"GitHub didn't merge it: {e}") from e
    try:
        facts = await github.pr_facts(ref)
    except github.GitHubError as e:
        ledger.update(store, loop_id, now, has_news=1)
        raise MergeRefused(f"GitHub didn't confirm the merge: {e}") from e
    evidence = github.evidence(facts)
    if facts.get("state") != "merged" or not evidence:
        ledger.update(store, loop_id, now, has_news=1)
        raise MergeRefused("GitHub hasn't confirmed the merge yet; I'll look again.")
    ledger.add_event(store, loop_id, now, "you", sha[:7], f"You merged {sha[:7]} from Pulse")
    ledger.update(store, loop_id, now, tapped="merge")
    ledger.close(store, loop_id, now, "odie", evidence)
    store.audit("user", "loop_merged", result_summary=f"{ref} at {sha[:7]}")
    return evidence


async def moved_on(store, loop: dict, ref: github.Ref, sha: str, now: datetime, facts: dict | None = None) -> bool:
    """Whether the head moved on from the tested commit (facts given, or read now); when it did, the card loses its
    Merge and the loop is due now, to test the new head. Head abc… still -> False; head def… now -> True; can't read
    -> False."""
    if facts is None:
        try:
            facts = await github.pr_facts(ref)
        except github.GitHubError:
            return False
    if facts.get("head_sha") == sha:
        return False
    pr_test.uncard(store, loop["id"])
    ledger.add_event(store, loop["id"], now, "gh", str(ref), f"New commits since the test of {sha[:7]}: not merged")
    ledger.update(store, loop["id"], now, state="working", has_news=1, next_step="testing the new commits",
                  next_check_at=now.isoformat(timespec="seconds"))
    return True
