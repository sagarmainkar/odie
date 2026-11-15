"""What a bot knows that is private, and where that goes with it (spike, Nov 2026).

In a chat, "private" lives in the turn (turn.PRIVATE, turn.READ) and under the chat's session id in the store
(guard.private_of / read_of): once a chat has read a signed-in page or the user's mail, words leaving it ask first.
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
    """The signed-in sites and the user's own things (mail, notes) a chat, job or bot has read: ({"amazon.in"}, {"your mail"})."""
    return guard.private_of(store, key), guard.read_of(store, key)


def carry(store: Store, key: str, sites: set, reads: set) -> None:
    """Mark a chat, job or bot private with these sites and reads (kept; nothing is ever taken off)."""
    for site in sites:
        guard.remember(store, key, site)
    for label in reads:
        guard.remember_read(store, key, label)


def of_this_turn(store: Store, key: str | None) -> tuple[set, set]:
    """What the running turn has read, plus what its chat or job already kept: the chat calling ask_bot, or the chief
    calling ask_bots. A chat that read your amazon.in orders this turn -> ({"amazon.in"}, set())."""
    sites = set(turn.private_sites())
    reads = set(turn.read_sources())
    if key:
        kept_sites, kept_reads = marks_of(store, key)
        sites |= kept_sites
        reads |= kept_reads
    return sites, reads


def at_start(store: Store, job_id: str, bot_name: str) -> tuple[set, set]:
    """What a bot's run starts out knowing is private: its job's marks (the chat's or chief's, carried at start, and
    an earlier run's) and its bot's (its notes). A fresh bot on a fresh job -> (set(), set())."""
    job_sites, job_reads = marks_of(store, job_id)
    bot_sites, bot_reads = marks_of(store, bot_key(bot_name))
    return job_sites | bot_sites, job_reads | bot_reads


def at_end(store: Store, job_id: str, bot_name: str) -> tuple[set, set]:
    """After a bot's run: what its turn read is kept under its job and its bot (so the next run and its notes stay
    private). Returns what it read, for the chat or chief it reports to."""
    sites = set(turn.private_sites())
    reads = set(turn.read_sources())
    carry(store, job_id, sites, reads)
    carry(store, bot_key(bot_name), sites, reads)
    return sites, reads


def job_is_private(store: Store, job_id: str) -> bool:
    """Has this job read something private? Its report then carries it. shopper's orders job -> True; a web search
    job -> False."""
    sites, reads = marks_of(store, job_id)
    return bool(sites or reads)
