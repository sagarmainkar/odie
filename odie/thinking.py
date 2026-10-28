"""Think harder, kept by Odie for each chat, so every app (the web app in any browser, the Mac app) sees and sends the
same choice. A chat that hasn't been set starts with the default, and the default is the last choice made in any chat.
Kept in the store's settings as "chat.thinking": {"default": bool, "chats": {session_id: bool}}, the latest KEEP chats
only (an older chat that comes back starts from the default again)."""
from __future__ import annotations

KEY = "chat.thinking"
KEEP = 300               # chats remembered; one a day plus the odd new chat or thread is under a year of them
FIRST_DEFAULT = False    # before any choice was made: as every turn from the Mac app ran until now


def _load(store) -> dict:
    saved = store.get_setting(KEY) or {}
    default = bool(saved.get("default", FIRST_DEFAULT))
    chats = {str(sid): bool(on) for sid, on in (saved.get("chats") or {}).items()}
    return {"default": default, "chats": chats}


def _save(store, default_on: bool, chats: dict[str, bool]) -> None:
    """Save the default and the chats, the latest KEEP only (the dict keeps them oldest first)."""
    while len(chats) > KEEP:
        oldest = next(iter(chats))
        del chats[oldest]
    store.set_setting(KEY, {"default": default_on, "chats": chats})


def default(store) -> bool:
    """What a chat that hasn't been set starts with: the last choice made in any chat (off before the first)."""
    return _load(store)["default"]


def get(store, session_id: str) -> bool:
    """This chat's Think harder: its own when it has one, else the default. Saves nothing.
      a chat set to on, default off  -> True
      a chat never set, default on   -> True
      a chat never set, default off  -> False"""
    saved = _load(store)
    chats = saved["chats"]
    if session_id in chats:
        return chats[session_id]
    return saved["default"]


def put(store, session_id: str, on: bool) -> bool:
    """Set this chat's Think harder, and make it the default for chats that haven't been set. Returns it."""
    saved = _load(store)
    chats = saved["chats"]
    chats.pop(session_id, None)  # re-added at the end: the most recently changed chats are the ones kept
    chats[session_id] = bool(on)
    _save(store, bool(on), chats)
    return bool(on)


def settle(store, session_id: str) -> bool:
    """This chat's Think harder for a turn about to run. A chat that hasn't been set keeps the default it starts with
    from now on, so a later change in another chat doesn't flip it halfway. The default itself is left as it is.
      a chat never set, default on       -> True, and the chat now says on
      a chat set to off, default on      -> False"""
    saved = _load(store)
    chats = saved["chats"]
    if session_id in chats:
        return chats[session_id]
    chats[session_id] = saved["default"]
    _save(store, saved["default"], chats)
    return saved["default"]


def event(session_id: str, on: bool) -> dict:
    """What the live stream (/api/events) carries when a chat's Think harder changes."""
    return {"type": "thinking", "session_id": session_id, "on": bool(on)}
