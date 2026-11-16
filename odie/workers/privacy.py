"""What a bot knows that is private, and where that goes with it (spike, Nov 2026).

"Private" means a signed-in page was read: in a chat it lives in the turn (turn.PRIVATE) and under the chat's session
id in the store (guard.private_of); from then on, words leaving it ask first. Reading the user's own mail, notes or
memory no longer makes anything private (16 Nov 2026: it blocked ordinary work), so the "reads" half of every pair
below is always empty; the pairs keep their shape for the callers.
A bot carries the same marks, under its job's id, from everywhere private words can reach it:
- the chat that started it (its brief may hold what the chat read),
- the chief that asked it (the chief's brief may hold what another teammate read),
- its own earlier runs (a scheduled bot is told its last report) and its notes (notes.md outlives every job), kept
  under the bot's own key, "bot:<name>".
And back out: what a bot read marks its job, its bot, and the chief or chat it reports to.

A private bot's web search, fetch and other sites wait for the user's tap, as in a private chat."""
from __future__ import annotations

from odie.agent import turn
from odie.signin import guard
from odie.store.db import Store


def bot_key(name: str) -> str:
    """Where a bot's own lasting privacy is kept: "shopper" -> "bot:shopper"."""
    return f"bot:{name}"


def marks_of(store: Store, key: str) -> tuple[set, set]:
    """The signed-in sites a chat, job or bot has read, and an empty second set (mail and notes no longer count):
    ({"amazon.in"}, set())."""
    return guard.private_of(store, key), set()


def carry(store: Store, key: str, sites: set, reads: set) -> None:
    """Mark a chat, job or bot private with these signed-in sites (kept; nothing is ever taken off). `reads` (mail,
    notes) is taken for the callers' sake and ignored: those no longer make anything private."""
    for site in sites:
        guard.remember(store, key, site)


def of_this_turn(store: Store, key: str | None) -> tuple[set, set]:
    """What the running turn has read, plus what its chat or job already kept: the chat calling ask_bot, or the chief
    calling ask_bots. A chat that read your amazon.in orders this turn -> ({"amazon.in"}, set())."""
    sites = set(turn.private_sites())
    if key:
        kept_sites, _ = marks_of(store, key)
        sites |= kept_sites
    return sites, set()


CLEARED = "bots.cleared."  # + a job id: the marks the user let that job work past with one tap, {"sites", "reads"}


def cleared_of(store: Store, job_id: str) -> tuple[set, set]:
    """What the user let this job work past (clear). None yet -> (set(), set())."""
    saved = store.get_setting(CLEARED + job_id) or {}
    return set(saved.get("sites") or ()), set(saved.get("reads") or ())


def clear(store: Store, job_id: str, sites: set, reads: set) -> None:
    """The user's one tap at a job's start: these marks no longer make this job's steps ask. Only these: a signed-in
    page it reads later still does."""
    had_sites, had_reads = cleared_of(store, job_id)
    store.set_setting(CLEARED + job_id, {"sites": sorted(had_sites | sites), "reads": sorted(had_reads | reads)})


def at_start(store: Store, job_id: str, bot_name: str) -> tuple[set, set]:
    """What a bot's run starts out knowing is private: its job's marks (the chat's or chief's, carried at start, and
    an earlier run's) and its bot's (its notes), less what the user cleared for this job with a tap.
    A fresh bot on a fresh job -> (set(), set()); a job from a chat that read your amazon.in orders ->
    ({"amazon.in"}, set()); the same after the user's Allow at its start -> (set(), set())."""
    job_sites, job_reads = marks_of(store, job_id)
    bot_sites, bot_reads = marks_of(store, bot_key(bot_name))
    ok_sites, ok_reads = cleared_of(store, job_id)
    return (job_sites | bot_sites) - ok_sites, (job_reads | bot_reads) - ok_reads


def of_lead_now(store: Store, job_id: str) -> tuple[set, set]:
    """What a chief passes to a teammate it asks now: what its run has read (its turn) and what its job carries, less
    what the user cleared for the job at its start. Cleared "flipkart.com", then a teammate read amazon.in ->
    ({"amazon.in"}, set())."""
    sites, reads = of_this_turn(store, job_id)
    ok_sites, ok_reads = cleared_of(store, job_id)
    return sites - ok_sites, reads - ok_reads


def what_words(sites: set, reads: set) -> str:
    """What a job carries, for the one tap: ({"amazon.in"}, set()) -> "your signed-in amazon.in";
    ({"amazon.in", "flipkart.com"}, set()) -> "your signed-in amazon.in and your signed-in flipkart.com"."""
    parts = [f"your signed-in {s}" for s in sorted(sites)] + sorted(reads)
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def at_end(store: Store, job_id: str, bot_name: str) -> tuple[set, set]:
    """After a bot's run: what its turn read is kept under its job and its bot (so the next run and its notes stay
    private). Returns what it read, for the chat or chief it reports to."""
    sites = set(turn.private_sites())
    carry(store, job_id, sites, set())
    carry(store, bot_key(bot_name), sites, set())
    return sites, set()


def job_is_private(store: Store, job_id: str) -> bool:
    """Has this job read a signed-in page? Its report then carries it. shopper's orders job -> True; a web search
    job -> False; a job that read your mail -> False."""
    sites, reads = marks_of(store, job_id)
    return bool(sites or reads)
