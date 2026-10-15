"""Setup's checklist and thread, in the store's "setup" setting. An install that already has chats counts as set up
(the owner's never sees Setup); "Run setup again" clears the flag."""
from __future__ import annotations

STEPS = ("brain", "names", "vault", "embeddings", "photos", "search", "voice", "apps", "phone")
SKIPPABLE = frozenset(STEPS) - {"brain", "names"}
KEY = "setup"


def _fresh() -> dict:
    return {"done": False, "steps": {s: "todo" for s in STEPS}, "thread": [], "fails": {}, "was_done": False}


def get(store) -> dict:
    s = store.get_setting(KEY)
    base = _fresh()
    if s:
        base.update({k: v for k, v in s.items() if k in base})
        base["steps"] = {**_fresh()["steps"], **(s.get("steps") or {})}
    return base


def _save(store, s: dict) -> dict:
    store.set_setting(KEY, s)
    return s


def is_done(store) -> bool:
    s = store.get_setting(KEY)
    if s is None:  # never started: done for an install that already chats
        return store.has_chats()
    return bool(s.get("done"))


def current(s: dict) -> str | None:
    return next((step for step in STEPS if s["steps"][step] == "todo"), None)


def mark(store, step: str, status: str) -> dict:
    """Setup finishes itself when no step is left to do."""
    s = get(store)
    s["steps"][step] = status
    if current(s) is None:
        s["done"] = True
    return _save(store, s)


def note_failure(store, step: str) -> int:
    s = get(store)
    s["fails"][step] = int(s["fails"].get(step, 0)) + 1
    _save(store, s)
    return s["fails"][step]


def add_to_thread(store, role: str, text: str, note: bool = False) -> dict:
    """note: a line from Odie itself (a key was saved, a step skipped on the screen), kept for the model, not shown.
    role "log": a tool the model called and what came back, kept only for the transcript (scripts/conversation.sh)."""
    s = get(store)
    entry = {"role": role, "text": text, **({"note": True} if note else {})}
    s["thread"] = [*s["thread"], entry][-200:]
    return _save(store, s)


def finish(store) -> dict:
    s = get(store)
    s["steps"] = {k: ("skipped" if v == "todo" and k in SKIPPABLE else v) for k, v in s["steps"].items()}
    s["done"] = True
    return _save(store, s)


def restart(store) -> dict:
    """Run setup again. Steps that were skipped come back and the rest stay done, so setup finishes only what was left;
    with nothing skipped, every step after the brain comes back, to change any of them. It remembers setup was done
    before, so it can be left with everything as it is."""
    prev = get(store)
    was = is_done(store) or bool(prev.get("was_done"))
    if any(v == "skipped" for v in prev["steps"].values()):
        steps = {k: ("todo" if v == "skipped" else v) for k, v in prev["steps"].items()}
    else:
        steps = {k: ("done" if k == "brain" and v == "done" else "todo") for k, v in prev["steps"].items()}
    return _save(store, {**_fresh(), "steps": steps, "was_done": was})


def can_leave(store) -> bool:
    """Setup that was finished before (or an install that already chats) can be left, keeping everything as it is."""
    s = get(store)
    return not s["done"] and (bool(s.get("was_done")) or store.has_chats())


def leave(store) -> dict:
    """Leave setup again, everything kept as it is. ValueError for a new install: it has to be set up."""
    if not can_leave(store):
        raise ValueError("This install hasn't been set up yet: the brain and your name come first.")
    return _save(store, {**get(store), "done": True})
