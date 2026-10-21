"""Up next's pictures (odie.photos.cards): a birthday or a calendar event gets a photo of the person its title names, as
Photos names people, or else of a thing one of its words names (a Photos label); nothing matches -> no picture."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie import upcoming
from odie.photos import cards
from odie.photos import settings as photo_settings
from odie.store.db import Store
from odie.vault import settings as vault_settings
from tests.test_photos_index import row

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

LIBRARY = [
    row("A1", "2026-08-01T10:00:00", people=["Asha Rao", "Dev"], favorite=True, big="/lib/a1.jpeg"),  # a favourite, with Dev
    row("A2", "2026-09-01T10:00:00", people=["Asha Rao"], big="/lib/a2.jpeg"),                        # Asha alone, newest
    row("A3", "2025-01-01T10:00:00", people=["Asha Rao"], big="/lib/a3.jpeg"),                        # Asha alone, older
    row("A4", "2026-10-01T10:00:00", people=["Asha Rao"], kind="video", big="/lib/a4.mov"),           # a video: never
    row("A5", "2026-10-02T10:00:00", people=["Asha Rao"], screenshot=True, big="/lib/a5.png"),        # a screenshot: never
    row("A6", "2026-10-03T10:00:00", people=["Asha Rao"], big=None),                                  # no copy here: never
    row("M1", "2024-03-01T10:00:00", people=["Mira Iyer"], big="/lib/m1.jpeg"),
    row("M2", "2024-04-01T10:00:00", people=["Mira Shah"], big="/lib/m2.jpeg"),                       # two Miras
    # Photos keeps a holiday or an activity among its extras, not its labels
    row("D1", "2023-11-12T19:00:00", labels=["Lamp"], extras={"holidays": ["Diwali"]}, big="/lib/d1.jpeg"),
    row("D2", "2024-11-01T19:00:00", labels=["Candle"], extras={"holidays": ["Diwali"], "activities": ["Celebration"]},
        favorite=True, big="/lib/d2.jpeg"),
    row("T1", "2024-02-01T10:00:00", labels=["Text"], extras={"detected_text": ["Dentist"]}, big="/lib/t1.jpeg"),  # never
    row("C1", "2024-06-01T10:00:00", labels=["Birthday", "Cake"], big="/lib/c1.jpeg"),
]


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    photo_settings.put(s, on=True)
    vault_settings.index_for(s).index_photos(LIBRARY)
    cards.forget()
    yield s
    cards.forget()


def picture(store, title):
    return cards.picture_for(title, cards.library_of(vault_settings.index_for(store)))


def test_a_birthday_finds_the_person_alone_first_then_a_favourite_then_the_newest(store):
    assert picture(store, "Asha Rao birthday") == "A2"  # alone and newest beats the favourite group photo
    assert picture(store, "Dinner with Dev") == "A1"     # Dev's only picture


def test_a_first_name_alone_counts_only_when_photos_knows_one_person_by_it(store):
    assert picture(store, "Asha's birthday") == "A2"     # the only Asha in Photos
    assert picture(store, "Mira birthday") is None       # two Miras: neither is guessed
    assert picture(store, "Mira Shah birthday") == "M2"  # the whole name settles it


def test_without_a_person_a_word_that_is_a_label_or_a_holiday_finds_its_pictures(store):
    assert picture(store, "Diwali at home") == "D2"      # the favourite first
    assert picture(store, "Office celebration") == "D2"  # an activity Photos saw
    assert picture(store, "Candle making") == "D2"       # a plain label
    assert picture(store, "Udo birthday") is None         # no such person; "birthday" never picks someone else's cake


def test_nothing_matching_means_no_picture(store):
    assert picture(store, "Dentist") is None
    assert picture(store, "") is None


def test_videos_screenshots_and_pictures_without_a_copy_are_never_chosen(store):
    library = cards.library_of(vault_settings.index_for(store))
    assert {p.uuid for p in library.pictures} == {"A1", "A2", "A3", "M1", "M2", "D1", "D2", "T1", "C1"}


def test_which_cards_get_a_picture():
    assert cards.wants_picture({"source": "calendar", "kind": "meeting"})
    assert cards.wants_picture({"source": "task", "kind": "birthday"})
    assert not cards.wants_picture({"source": "task", "kind": "bill"})
    assert not cards.wants_picture({"source": "sms", "kind": "delivery"})


async def test_up_next_carries_the_picture_address_for_a_matching_event(store):
    store.set_setting("watch.card", {"events": [
        {"id": "e1", "title": "Asha Rao birthday", "start": "2026-10-22", "badges": []},
        {"id": "e2", "title": "Dentist", "start": "2026-10-23T10:00:00+05:30", "badges": []}]})
    got = {it["title"]: it for it in (await upcoming.build(store, NOW))["items"]}
    assert got["Asha Rao birthday"]["photo"] == "/api/photos/A2/big"
    assert "photo" not in got["Dentist"]


async def test_with_photos_off_no_card_gets_a_picture(store):
    photo_settings.put(store, on=False)
    store.set_setting("watch.card", {"events": [{"id": "e1", "title": "Asha Rao birthday", "start": "2026-10-22"}]})
    [item] = (await upcoming.build(store, NOW))["items"]
    assert "photo" not in item
