"""The built-in notes index: chunks by headings, keyword search (FTS5), and reading that never leaves the vault."""
import os
import shutil
import time
from pathlib import Path

import pytest

from odie.vault.chunks import MAX_WORDS, parse
from odie.vault.index import VaultIndex

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    shutil.copytree(SAMPLE, v)
    return v


@pytest.fixture
def index(vault, tmp_path):
    ix = VaultIndex(tmp_path / "vault-index.db", vault)
    ix.scan()
    return ix


def test_chunks_split_by_headings_and_size():
    small = "# Trip\n\n## Day 1\nBeach.\n\n## Day 2\nFort.\n"
    [only] = parse(small, "Trip").chunks
    assert only.heading == "Trip" and "Beach." in only.text and "Fort." in only.text and "## Day 2" in only.text
    para = " ".join(["word"] * 120)
    big = "# Notes\n\n## Long\n" + "\n\n".join([para] * 12) + "\n\n## After\nTail.\n"
    chunks = parse(big, "Notes").chunks
    assert len(chunks) >= 2 and all(len(c.text.split()) <= MAX_WORDS for c in chunks)
    assert chunks[0].heading == "Notes > Long" and chunks[-1].text.rstrip().endswith("Tail.")


def test_parse_reads_links_tags_aliases_and_title():
    p = parse((SAMPLE / "1-Projects" / "Trip to Goa.md").read_text(), "Trip to Goa")
    assert p.title == "Goa trip" and p.aliases == ("Goa", "Beach trip")
    assert set(p.tags) == {"travel", "family", "beach"}
    h = parse((SAMPLE / "Home.md").read_text(), "Home")
    assert h.title == "Home" and h.links == ("Trip to Goa", "Recipes/Dal") and h.tags == ("index",)
    assert parse("No heading here.", "plain-name").title == "plain-name"


def test_scan_indexes_only_notes_and_skips_ignored_folders(index, vault, tmp_path):
    assert index.status()["notes"] == 3
    assert {h.path for h in index.keyword("lentils")} == {"Recipes/Dal.md"}  # not .obsidian, not .trash
    (vault / "Private").mkdir()
    (vault / "Private" / "Secret.md").write_text("# Secret\nlentils\n")
    ix = VaultIndex(tmp_path / "other.db", vault, ignore=["Private"])
    ix.scan()
    assert {h.path for h in ix.keyword("lentils")} == {"Recipes/Dal.md"}


def test_keyword_search_ranks_and_filters(index, vault):
    hits = index.keyword("flight to Goa")
    assert hits[0].path == "1-Projects/Trip to Goa.md" and hits[0].note == "Goa trip" and hits[0].updated
    assert index.keyword("family", folder="Recipes")[0].path == "Recipes/Dal.md"
    assert [h.path for h in index.keyword("family", tags=["travel"])] == ["1-Projects/Trip to Goa.md"]
    old = vault / "Recipes" / "Dal.md"
    os.utime(old, (time.time() - 90 * 86400, time.time() - 90 * 86400))
    index.scan()
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
    assert "Recipes/Dal.md" not in {h.path for h in index.keyword("family", since=since)}
    assert index.keyword("whistles", k=1)[0].text.count("pressure cook") == 1


def test_rescan_follows_changes(index, vault):
    dal = vault / "Recipes" / "Dal.md"
    dal.write_text("# Dal\nNow with tamarind instead.\n")
    future = time.time() + 5
    os.utime(dal, (future, future))
    (vault / "Home.md").rename(vault / "Start.md")
    (vault / "1-Projects" / "Trip to Goa.md").unlink()
    out = index.scan()
    assert out["removed"] == 2 and out["added"] == 1 and out["updated"] == 1
    assert index.keyword("lentils") == [] and index.keyword("tamarind")[0].path == "Recipes/Dal.md"
    assert index.keyword("Calangute") == [] and index.keyword("Welcome")[0].path == "Start.md"
    assert index.status()["notes"] == 2


def test_reading_stays_inside_the_vault(index, vault, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\nprivate")
    (vault / "link.md").symlink_to(outside)
    for bad in ("../outside.md", str(outside), "link.md", "link", "photo.png", "photo", "../../etc/passwd",
                "/etc/passwd", "Nope"):
        assert index.resolve(bad) is None and index.read(bad) is None, bad
    index.scan()
    assert "private" not in " ".join(h.text for h in index.keyword("private"))


def test_resolve_by_title_alias_and_path(index, vault):
    trip = vault / "1-Projects" / "Trip to Goa.md"
    for name in ("1-Projects/Trip to Goa.md", "1-Projects/Trip to Goa", "Trip to Goa", "trip to goa", "Goa trip", "Beach trip"):
        assert index.resolve(name) == trip.resolve(), name
    assert index.read("Goa").startswith("---\ntitle: Goa trip")
    assert len(index.read("Goa", limit=40)) <= 41


def test_linked_finds_links_backlinks_and_shared_tags(index):
    home = index.linked("Home")
    assert home["links"] == ["1-Projects/Trip to Goa.md", "Recipes/Dal.md"] and home["backlinks"] == ["Recipes/Dal.md"]
    assert index.linked("Dal")["shared_tags"] == ["1-Projects/Trip to Goa.md"]  # both #family
    assert index.linked("Nope") == {"links": [], "backlinks": [], "shared_tags": []}


def test_a_question_without_words_finds_nothing(index):
    assert index.keyword("?!") == [] and index.keyword("") == [] and index.keyword("the and of") == []


def test_an_unreadable_note_is_skipped_not_fatal(index, vault, tmp_path):
    locked = vault / "Locked.md"
    locked.write_text("# Locked\nlentils too\n")
    locked.chmod(0)
    try:
        ix = VaultIndex(tmp_path / "fresh.db", vault)
        out = ix.scan()
        assert out["notes"] >= 3 and ix.keyword("Calangute")  # the others are indexed
        assert "Locked.md" in (ix.status()["scan_warning"] or "")
    finally:
        locked.chmod(0o644)


def test_filters_reach_beyond_the_top_hits(vault, tmp_path):
    for i in range(80):
        (vault / f"Common {i}.md").write_text(f"# Common {i}\nlentils lentils lentils note {i}\n")
    (vault / "Pantry").mkdir()
    (vault / "Pantry" / "Shelf.md").write_text("# Shelf\nThe lentils jar is on the top shelf, behind the rice and flour and salt.\n")
    ix = VaultIndex(tmp_path / "many.db", vault)
    ix.scan()
    assert [h.path for h in ix.keyword("lentils", folder="Pantry")] == ["Pantry/Shelf.md"]
