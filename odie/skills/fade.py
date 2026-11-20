"""Learned skills fade (proactive design §18, 20 Nov): a skill Odie learned through a "Learn this?" card
(odie.loops.learning; installed on his Approve) that goes unused for FADE_DAYS is put away, never deleted: its folder
moves to skills-archive/, and a notice says so once, with Undo (which brings it back). Skills he asked for himself, or
wrote, never fade: like Hermes's curator, only what Odie learned on its own is tidied.

"Used" is a load_skill of it in any chat (odie.agent.callbacks notes it, once a day at most)."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from odie import config

FADE_DAYS = 30
LEARNED = "skills.learned"  # {name: {"at": installed, "used": last load or "", "loop": the card's loop id}}
FADED = "skills.faded"  # {"next": 2, "items": [{"id", "name", "at", "state", "said"}]}
REF = "faded:"


def archive_dir() -> Path:
    return config.settings.config_dir / "skills-archive"


def learned(store) -> dict:
    return dict(store.get_setting(LEARNED) or {})


def mark_learned(store, name: str, now: datetime, loop_id: int) -> None:
    """A skill installed from a "Learn this?" card: from now on it fades when unused."""
    kept = learned(store)
    kept[name] = {"at": now.isoformat(timespec="seconds"), "used": "", "loop": int(loop_id)}
    store.set_setting(LEARNED, kept)


def note_used(store, name: str, now: datetime) -> None:
    """A learned skill was loaded: its fade clock starts again. Written once a day at most; any other skill -> nothing."""
    kept = learned(store)
    entry = kept.get(name)
    if entry is None:
        return
    today = now.date().isoformat()
    if str(entry.get("used") or "")[:10] == today:
        return
    entry["used"] = now.isoformat(timespec="seconds")
    store.set_setting(LEARNED, kept)


def unused_too_long(entry: dict, now: datetime) -> bool:
    """Whether a learned skill should be put away: its last use (or its install, when it was never used) is more than
    FADE_DAYS ago. Installed 31 days ago, never used -> True; used 3 days ago -> False; installed yesterday -> False."""
    last = str(entry.get("used") or entry.get("at") or "")
    if not last:
        return False
    return now - datetime.fromisoformat(last) > timedelta(days=FADE_DAYS)


def faded(store) -> dict:
    found = store.get_setting(FADED) or {}
    return {"next": int(found.get("next") or 1), "items": list(found.get("items") or [])}


def free_folder(name: str, now: datetime) -> Path:
    """A folder in archive_dir no skill is in yet: the name, else the name and the day, else with a number after.
    "trip" free -> trip;  taken -> trip-2026-11-20;  that taken too -> trip-2026-11-20-2"""
    dest = archive_dir() / name
    if not dest.exists():
        return dest
    day = now.date().isoformat()
    dest = archive_dir() / f"{name}-{day}"
    n = 2
    while dest.exists():
        dest = archive_dir() / f"{name}-{day}-{n}"
        n += 1
    return dest


def fade(store, now: datetime, user_dir: Path) -> list[dict]:
    """Puts away each learned skill unused too long: its folder moves from user_dir to archive_dir (a name already
    there gets the day added), and its notice waits. Returns the notices made. A learned skill whose folder is gone
    (he removed it) is just forgotten."""
    kept = learned(store)
    notes = faded(store)
    made = []
    for name, entry in sorted(kept.items()):
        if not unused_too_long(entry, now):
            continue
        del kept[name]
        src = user_dir / name
        if not src.is_dir():
            continue
        archive_dir().mkdir(parents=True, exist_ok=True)
        dest = free_folder(name, now)
        shutil.move(str(src), str(dest))
        notice = {"id": notes["next"], "name": name, "folder": dest.name, "at": now.isoformat(timespec="seconds"),
                  "state": "on", "said": False}
        notes["next"] += 1
        notes["items"] = [*notes["items"], notice][-50:]
        made.append(notice)
    store.set_setting(LEARNED, kept)
    if made:
        store.set_setting(FADED, notes)
    return made


def notice_card(entry: dict) -> dict:
    """"Put away: X", said once, in the shape of every card (odie.watch.needs): Undo (back, as it was) and OK."""
    ref = f"{REF}{entry['id']}"
    why = (f"Odie learned the {entry['name']} skill but hasn't used it for {FADE_DAYS} days, so it's put away "
           "(not deleted). Undo brings it back.")
    return {"ref": ref, "title": f"Put away: {entry['name']}", "why": why, "brief": "", "icon": "spark", "badge": "",
            "ask": f"Tell me about the {entry['name']} skill",
            "main": {"label": "Undo", "action": "notice_undo", "value": ref},
            "other": {"label": "OK", "action": "dismiss", "value": ref},
            "pile": "alerts", "since": entry["at"], "decide": False, "evidence": []}


def notice_cards(store) -> list[dict]:
    return [notice_card(e) for e in faded(store)["items"] if e["state"] == "on" and not e["said"]]


def number_of(ref: str) -> int | None:
    """The notice a card's ref names: "faded:2" -> 2; "faded:x", "rule:2" -> None."""
    if not ref.startswith(REF) or not ref[len(REF):].isdigit():
        return None
    return int(ref[len(REF):])


def said(store, entry_id: int) -> bool:
    """His OK: the notice is said; the skill stays put away."""
    notes = faded(store)
    found = next((e for e in notes["items"] if e["id"] == int(entry_id)), None)
    if found is None:
        return False
    found["said"] = True
    store.set_setting(FADED, notes)
    return True


def restore(store, entry_id: int, now: datetime, user_dir: Path) -> str | None:
    """His Undo: the skill's folder goes back where it was and it is learned again, its clock starting today. Returns
    its name; None when there is no such notice, it was undone already, its folder is gone, or a skill of that name
    was installed since (nothing is written over)."""
    notes = faded(store)
    found = next((e for e in notes["items"] if e["id"] == int(entry_id)), None)
    if found is None or found["state"] != "on":
        return None
    src = archive_dir() / found.get("folder", found["name"])
    dest = user_dir / found["name"]
    if not src.is_dir() or dest.exists():
        return None
    user_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    found["state"] = "undone"
    found["said"] = True
    store.set_setting(FADED, notes)
    kept = learned(store)
    kept[found["name"]] = {"at": now.isoformat(timespec="seconds"), "used": "", "loop": 0}
    store.set_setting(LEARNED, kept)
    return found["name"]
