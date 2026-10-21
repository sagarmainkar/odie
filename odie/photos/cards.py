"""A picture for an Up next card (odie.upcoming): for a birthday, a celebration or a calendar event, a photo of the
person its title names, as Photos names people, or else of a thing one of its words names (a Photos label). Nothing
matches -> no picture, and the card stays as it was. Only while Photos is on in Settings; never a video, a screenshot
or a picture without a large copy on this Mac (VaultIndex.card_pictures)."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass

from odie.memory.search import STOPWORDS

log = logging.getLogger("odie.upcoming")

WORD = re.compile(r"[^\W_]+", re.UNICODE)
# Words that never pick a picture by label: a birthday's own words would bring someone else's cake.
NOT_LABELS = {"birthday", "bday", "bdy", "janmadin", "vadhdivas", "happy"}
SHORTEST_LABEL = 4  # "Diwali", "Beach" count; "Lab", "Sea" are too easily a word of something else
# Apple's extras that name a thing like a label does ("holidays": ["Diwali"]); never "detected_text", words seen in a picture
EXTRA_KINDS = ("holidays", "activities", "landmarks", "pets", "events")
PICTURE_KINDS = {"birthday", "celebration"}  # these get a picture from any source; everything else only from a calendar


@dataclass(frozen=True)
class Picture:
    uuid: str
    people: tuple[str, ...]  # as Photos names them: ("Asha Rao", "Dev")
    labels: frozenset[str]   # lower case, Photos' labels and its noteworthy extras: {"lamp", "diwali"}
    favorite: bool
    taken: str


@dataclass(frozen=True)
class Library:
    pictures: list[Picture]
    people: list[str]        # every name Photos gives anyone, once each
    labels: frozenset[str]   # every label, lower case

    @classmethod
    def of(cls, rows: list[dict]) -> Library:
        pictures = [Picture(uuid=r["uuid"], people=tuple(json.loads(r["people"] or "[]")), labels=labels_of(r),
                            favorite=bool(r["favorite"]), taken=r["taken"] or "") for r in rows]
        people = sorted({name for p in pictures for name in p.people})
        labels = frozenset(label for p in pictures for label in p.labels)
        return cls(pictures, people, labels)


def labels_of(row: dict) -> frozenset[str]:
    """A picture's labels and its noteworthy extras, lower case: labels ["Lamp"], extras {"holidays": ["Diwali"],
    "detected_text": ["SALE"]} -> {"lamp", "diwali"}."""
    labels = [label.lower() for label in json.loads(row["labels"] or "[]")]
    extras = json.loads(row.get("extras") or "{}")
    for kind in EXTRA_KINDS:
        labels += [value.lower() for value in extras.get(kind, [])]
    return frozenset(labels)


_cached: dict[str, Library] = {}  # by when the photos were read, so the library is parsed again only after a new read


def forget() -> None:
    """Drops the parsed library (tests, or a fresh read of Photos)."""
    _cached.clear()


def library_of(index) -> Library:
    """The index's usable pictures, parsed once per read of Photos."""
    read_at = index.photos_read_at()
    if read_at not in _cached:
        _cached.clear()
        _cached[read_at] = Library.of(index.card_pictures())
    return _cached[read_at]


def words_of(text: str) -> list[str]:
    """A title's words, lower case: "Asha's birthday!" -> ["asha", "s", "birthday"]."""
    return [w.lower() for w in WORD.findall(text or "")]


def has_run(words: list[str], run: list[str]) -> bool:
    """Whether `run` appears in `words` as consecutive words: (["asha", "rao", "birthday"], ["asha", "rao"]) -> True;
    (["rao", "asha"], ["asha", "rao"]) -> False."""
    n = len(run)
    return n > 0 and any(words[i:i + n] == run for i in range(len(words) - n + 1))


def people_named(title: str, people: list[str]) -> list[str]:
    """The Photos people a title names: someone's whole name in it as words, or their first name alone when nobody
    else in Photos shares it. Photos knows "Asha Rao", "Dev", "Mira Iyer" and "Mira Shah":
    "Asha Rao birthday" -> ["Asha Rao"]; "Asha's birthday" -> ["Asha Rao"]; "Dinner with Dev" -> ["Dev"];
    "Mira birthday" -> [] (two Miras); "Mira Shah birthday" -> ["Mira Shah"]."""
    words = words_of(title)
    first_names = [words_of(name)[0] for name in people if words_of(name)]
    named = []
    for name in people:
        parts = words_of(name)
        if not parts:
            continue
        whole = has_run(words, parts)
        first = parts[0]
        first_alone = len(parts) > 1 and first in words and first_names.count(first) == 1
        if whole or first_alone:
            named.append(name)
    return named


def label_named(title: str, labels: frozenset[str]) -> str | None:
    """A word of the title that is a Photos label, for an event without a person: "Diwali at home" -> "diwali";
    "Udo birthday" -> None ("birthday" never counts); "Lab test" -> None (too short to trust)."""
    for word in words_of(title):
        if len(word) < SHORTEST_LABEL or word in STOPWORDS or word in NOT_LABELS:
            continue
        if word in labels:
            return word
    return None


def best(pictures: list[Picture], people: list[str]) -> str | None:
    """The picture to show, from the ones that match: for a person, one where they are the only one named first; then
    a favourite; then the newest. The same library gives the same choice, so a card keeps its picture all day.
    Asha alone in May, Asha with Dev as a favourite in August -> the May one."""
    if not pictures:
        return None

    def rank(p: Picture) -> tuple:
        alone = bool(people) and len(p.people) == len(people)
        return (alone, p.favorite, p.taken)

    return max(pictures, key=rank).uuid


def picture_for(title: str, library: Library) -> str | None:
    """The uuid of the picture for a card with this title, or None. A person the title names first (every one of
    them in the picture), then a label; nothing matching -> None. "Asha Rao birthday" -> Asha's picture; "Diwali at
    home" -> a Diwali picture; "Dentist" -> None."""
    people = people_named(title, library.people)
    if people:
        with_them = [p for p in library.pictures if all(name in p.people for name in people)]
        return best(with_them, people)
    label = label_named(title, library.labels)
    if label:
        with_label = [p for p in library.pictures if label in p.labels]
        return best(with_label, [])
    return None


def wants_picture(item: dict) -> bool:
    """Whether an Up next card looks for a picture: a birthday or a celebration from anywhere, and any calendar event.
    {"source": "calendar", "kind": "meeting"} -> True; {"source": "task", "kind": "birthday"} -> True;
    {"source": "task", "kind": "bill"} -> False; an SMS delivery -> False."""
    if item.get("kind") in PICTURE_KINDS:
        return True
    return item.get("source") == "calendar"


def add_pictures(store, items: list[dict]) -> None:
    """Gives each card that wants one its picture's address ("photo": "/api/photos/<uuid>/big"), when Photos is on and
    one matches. A library that can't be read leaves every card as it was, and the log says why."""
    from odie.photos import settings as photo_settings
    from odie.vault import settings as vault_settings
    if not photo_settings.is_on(store):
        return
    index = vault_settings.index_for(store)
    if index is None:
        return
    try:
        library = library_of(index)
    except (sqlite3.Error, OSError, ValueError) as e:
        log.warning("up next: the photos couldn't be read for pictures: %s", e)
        return
    for item in items:
        if not wants_picture(item):
            continue
        uuid = picture_for(str(item.get("title") or ""), library)
        if uuid:
            item["photo"] = f"/api/photos/{uuid}/big"
