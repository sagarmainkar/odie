"""Which brain (chat model) thinks for whom. Everyday Odie uses the model chosen in Settings → Brain, with the fallback
when nothing is chosen (odie.models.resolve_selection). A personality uses everyday Odie's ("Same as Odie", the
default) or a brain picked for it alone, kept in the setting "brain:<its id>".

A brain picked for a personality never falls back: when its provider is no longer set up, the personality's turns are
refused (BrainGone) rather than sent to another model, because the fallback may be a cloud one and its words are meant
only for the model the user chose for it. Every model call made for a thread asks here which brain to use
(for_thread), so a reminder, the memory review, the trim and a making job's writer all follow the thread's owner."""
from __future__ import annotations

from odie import personalities
from odie.models import Selection, all_providers, resolve_selection
from odie.store.db import Store

GONE = ("{name}'s brain ({model} on {provider}) isn't set up any more, so {name} can't answer. Pick another brain "
        "for {name} in Settings → Brain, or set it to \"Same as Odie\".")
NO_ONE = "This thread's personality was deleted, so nobody can answer here."


class BrainGone(Exception):
    """The brain picked for a personality can't be used (its provider was removed), or the personality itself is gone.
    Its message is words for the user, which say what to do."""


def _key(pid: str) -> str:
    return f"brain:{pid}"


def own_pick(store: Store, pid: str) -> dict | None:
    """The brain picked for this personality alone, {"provider": …, "model": …}, or None for "Same as Odie" (and for
    everyday Odie itself, whose choice lives in Settings → Brain as it always has)."""
    if not pid:
        return None
    return store.get_setting(_key(pid))


def choose(store: Store, pid: str, provider: str, model: str) -> None:
    """Give this personality a brain of its own."""
    if not pid:
        raise ValueError("everyday Odie's brain is chosen in Settings → Brain (model.chat)")
    store.set_setting(_key(pid), {"provider": provider, "model": model})


def same_as_odie(store: Store, pid: str) -> None:
    """Back to "Same as Odie": the personality thinks with whatever everyday Odie uses. Also how a deleted personality's
    pick is removed (personalities.delete)."""
    store.execute("delete from settings where key=?", (_key(pid),))


def for_personality(store: Store, pid: str) -> Selection:
    """The brain that thinks for this personality right now. Its own pick is used as it is or not at all.
      everyday Odie ("")                                -> Odie's choice, or the fallback (resolve_selection)
      Mira, "Same as Odie"                              -> the same as everyday Odie
      Mira, her own ollama / qwen3.8, Ollama set up     -> ollama / qwen3.8
      Mira, her own work-box / gemma, work-box removed  -> BrainGone (never the fallback, never Odie's)
      a personality that was deleted                    -> BrainGone"""
    if not pid:
        return resolve_selection(store, "chat")
    found = personalities.get(store, pid)
    if found is None:
        raise BrainGone(NO_ONE)
    pick = own_pick(store, pid)
    if pick is None:
        return resolve_selection(store, "chat")
    providers = {p.id: p for p in all_providers(store)}
    provider = providers.get(pick["provider"])
    if provider is None:
        raise BrainGone(GONE.format(name=found.name, model=pick["model"], provider=pick["provider"]))
    return Selection(provider, pick["model"], "chat")


def for_thread(store: Store, session_id: str | None) -> Selection:
    """The brain for anything sent to a model about this thread: the brain of whoever the thread belongs to, read from
    the thread's own row (personalities.of_session), never from a request.
      an everyday thread, or no thread (a background check) -> everyday Odie's
      a thread of Mira's                                   -> Mira's (for_personality)"""
    owner = personalities.of_session(store, session_id)
    return for_personality(store, owner)
