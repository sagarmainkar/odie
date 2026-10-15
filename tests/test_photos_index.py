"""Photos and videos in Odie's index, from what Apple's Photos already knows about each one (odie.photos.library reads
it; here the rows are made by hand): keyword search over people, labels, places, albums, dates and Apple's extras,
with filters for who, where, when, which album and photo or video; the row a thumbnail route needs; counts; and a
re-read that keeps the vectors of pictures still there."""
import shutil
from array import array
from pathlib import Path

import pytest

from odie.photos.library import PhotoRow
from odie.vault.index import VaultIndex

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"


def row(uuid: str, taken: str, people=(), labels=(), place="", city="", country="", albums=(), extras=None, kind="photo",
        thumb="/lib/t.jpeg", big=None, favorite=False, screenshot=False) -> PhotoRow:
    return PhotoRow(uuid=uuid, kind=kind, taken=taken, people=list(people), labels=list(labels), place=place, city=city,
                    country=country, albums=list(albums), extras=dict(extras or {}), favorite=favorite, screenshot=screenshot,
                    width=4032, height=3024, thumb=thumb, big=big)


ROWS = [
    row("A1", "2024-05-16T11:09:23", people=["Asha", "Dev"], labels=["Beach", "Sea", "Sunset"], place="Baga Beach, Goa, India",
        city="Goa", country="India", albums=["Goa 2024"], extras={"season": ["Summer"], "activities": ["Beach"]}, big="/lib/b.jpeg"),
    row("B2", "2024-05-17T20:30:00", people=["Asha"], labels=["Food", "Pasta", "Restaurant"], place="Anjuna, Goa, India",
        city="Goa", country="India", albums=["Goa 2024"], extras={"times_of_day": ["Night"]}),
    row("C3", "2023-11-12T18:00:00", people=["Dev", "Mira"], labels=["Lamp", "Celebration"], place="Pune, India", city="Pune",
        country="India", albums=["Diwali"], extras={"holidays": ["Diwali"]}),
    row("D4", "2022-03-01T09:00:00", people=[], labels=["Dog", "Grass"], place="", albums=[], thumb=None),
    row("V5", "2024-05-16T17:00:00", people=["Asha"], labels=["Sea", "Boat"], place="Baga Beach, Goa, India", city="Goa",
        country="India", albums=["Goa 2024"], kind="video"),
    row("S6", "2025-01-02T10:00:00", labels=["Text", "Document"], screenshot=True),
]


@pytest.fixture
def index(tmp_path):
    ix = VaultIndex(tmp_path / "odie-index.db", None)  # photos alone: no notes folder at all
    ix.index_photos(ROWS)
    return ix


def test_index_photos_counts_and_status(index):
    st = index.status()
    assert st["notes"] == 0 and st["photos"] == 5 and st["videos"] == 1 and st["photo_vectors"] == 0
    assert st["photos_at"]


def test_words_match_people_labels_places_albums_and_dates(index):
    assert [h.uuid for h in index.search_photos("beach sunset")][0] == "A1"
    assert {h.uuid for h in index.search_photos("goa")} == {"A1", "B2", "V5"}
    assert [h.uuid for h in index.search_photos("mira")] == ["C3"]
    assert [h.uuid for h in index.search_photos("diwali")] == ["C3"]  # the album and Apple's holiday
    assert [h.uuid for h in index.search_photos("dog")] == ["D4"]
    assert {h.uuid for h in index.search_photos("may 2024")} == {"A1", "B2", "V5"}
    assert index.search_photos("xylophone") == []


def test_filters_narrow_without_words_newest_first(index):
    assert [h.uuid for h in index.search_photos("", people=["asha"])] == ["B2", "V5", "A1"]
    assert [h.uuid for h in index.search_photos("", people=["Asha", "dev"])] == ["A1"]  # everyone named must be in it
    assert [h.uuid for h in index.search_photos("", place="pune")] == ["C3"]
    assert [h.uuid for h in index.search_photos("", album="goa")] == ["B2", "V5", "A1"]
    assert [h.uuid for h in index.search_photos("", since="2024-05-17")] == ["S6", "B2"]
    assert [h.uuid for h in index.search_photos("", since="2024-05-16", until="2024-05-16")] == ["V5", "A1"]
    assert [h.uuid for h in index.search_photos("", kind="video")] == ["V5"]
    assert [h.uuid for h in index.search_photos("sea", kind="photo")] == ["A1"]
    assert [h.uuid for h in index.search_photos("", people=["nobody"])] == []


def test_a_hit_carries_what_a_reply_needs(index):
    [h] = index.search_photos("pasta")
    assert (h.uuid, h.kind, h.taken, h.place, h.people, h.albums) == ("B2", "photo", "2024-05-17", "Anjuna, Goa, India", ["Asha"], ["Goa 2024"])
    assert h.labels == ["Food", "Pasta", "Restaurant"] and h.has_thumb is True
    [d] = index.search_photos("dog")
    assert d.has_thumb is False  # nothing of it on this computer: metadata only


def test_the_photo_row_for_a_thumbnail_route(index):
    p = index.photo("A1")
    assert p["thumb"] == "/lib/t.jpeg" and p["big"] == "/lib/b.jpeg" and p["kind"] == "photo"
    assert index.photo("B2")["big"] is None and index.photo("nope") is None


def test_a_reread_keeps_vectors_of_pictures_still_there_and_drops_the_rest(index):
    with index._db() as c:
        c.execute("insert into vectors values ('photo', 'A1', ?)", (array("f", [1.0, 0.0]).tobytes(),))
        c.execute("insert into vectors values ('photo', 'C3', ?)", (array("f", [0.0, 1.0]).tobytes(),))
    index.index_photos([r for r in ROWS if r.uuid != "C3"])
    with index._db() as c:
        assert [r["ref"] for r in c.execute("select ref from vectors where kind='photo'")] == ["A1"]
    assert index.status()["photos"] == 4 and index.status()["photo_vectors"] == 1
    assert index.photo("C3") is None and index.search_photos("diwali") == []


def test_forget_photos_clears_everything_about_them(index):
    with index._db() as c:
        c.execute("insert into vectors values ('photo', 'A1', ?)", (array("f", [1.0, 0.0]).tobytes(),))
    index.forget_photos()
    st = index.status()
    assert st["photos"] == 0 and st["videos"] == 0 and st["photo_vectors"] == 0 and st["photos_at"] is None
    assert index.search_photos("goa") == []


def test_notes_and_photos_share_the_file(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(SAMPLE, vault)
    ix = VaultIndex(tmp_path / "odie-index.db", vault)
    ix.scan()
    ix.index_photos(ROWS)
    st = ix.status()
    assert st["notes"] > 0 and st["photos"] == 5
    assert ix.keyword("goa")  # the notes side still answers
    assert ix.search_photos("goa")
