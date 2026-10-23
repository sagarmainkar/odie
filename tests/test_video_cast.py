"""A dialogue video's cast (phase 2): character sheets read from the user's own folder, so the cast looks and sounds
the same in every video of a work; acts in the script give each scene's ages."""
import pytest

from odie.video import cast, dialogue

MIRA = """---
id: mira
display_name: Mira
canonical: "A tall woman in her thirties, short silver hair, a long green oilskin coat."
voice: af_bella
ages:
  - act: Chapter one
    age: 34
    ref: refs/mira-34.jpg
  - act: Chapter two
    age: 41
refs: [refs/mira-front.jpg]
asset: models/mira.glb
---
Speaks slowly; never smiles on the first line of a scene.
"""

TOBI = """---
id: Tobi
canonical: "A boy of twelve in a yellow raincoat, freckles, a red wool hat."
voice: Michael
---
"""


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "cast"
    (root / "refs").mkdir(parents=True)
    (root / "mira.md").write_text(MIRA)
    (root / "tobi.md").write_text(TOBI)
    (root / "README.md").write_text("Notes about the cast, no front matter.")
    (root / "refs" / "mira-front.jpg").write_bytes(b"jpg")
    (root / "refs" / "mira-34.jpg").write_bytes(b"jpg")
    return root


def test_scenes_carry_the_act_given_before_them():
    script = dialogue.parse("## Act: Chapter one\n## Scene: A\nMIRA: Hi.\n## Scene: B\nMIRA: Yo.\n"
                            "## Act: Chapter two\n## Scene: C\nMIRA: Bye.")
    assert [(scene.where, scene.act) for scene in script.scenes] == [("A", "Chapter one"), ("B", "Chapter one"),
                                                                      ("C", "Chapter two")]
    assert dialogue.from_data(script.as_data()).scenes[2].act == "Chapter two"
    assert dialogue.parse("MIRA: Hi.").scenes[0].act == ""


def test_a_cast_folder_reads_each_sheet_and_skips_other_notes(folder):
    found = {character.id: character for character in cast.read(folder)}
    assert sorted(found) == ["mira", "tobi"]
    mira = found["mira"]
    assert mira.display_name == "Mira" and mira.voice == "af_bella"
    assert mira.canonical.startswith("A tall woman in her thirties")
    assert mira.age_in("Chapter one") == 34 and mira.age_in("Chapter two") == 41 and mira.age_in("Epilogue") is None
    assert mira.notes == "Speaks slowly; never smiles on the first line of a scene."
    assert [path.name for path in mira.pictures()] == ["mira-front.jpg", "mira-34.jpg"]  # files that exist
    assert found["tobi"].display_name == "Tobi"  # no display_name: the id as written


def test_a_sheet_that_cant_be_read_is_named(folder):
    (folder / "broken.md").write_text("---\nid: [unclosed\n---\n")
    with pytest.raises(cast.CastProblem, match="broken.md"):
        cast.read(folder)


def test_two_sheets_for_one_id_are_refused(folder):
    (folder / "mira2.md").write_text("---\nid: Mira\n---\n")
    with pytest.raises(cast.CastProblem, match="mira"):
        cast.read(folder)


def test_a_folder_without_sheets_says_how_to_write_one(tmp_path):
    with pytest.raises(cast.CastProblem, match="id:"):
        cast.read(tmp_path)


def test_a_cast_folder_is_found_in_the_vault_by_its_path_there(folder, tmp_path):
    vault = tmp_path
    assert cast.find_folder("cast", vault_dir=str(vault)) == folder
    assert cast.find_folder(str(folder), vault_dir=None) == folder
    with pytest.raises(cast.CastProblem, match="No folder"):
        cast.find_folder("Stories/missing", vault_dir=str(vault))


def test_the_writer_reads_the_cast_word_for_word_with_each_scenes_ages_and_the_look(folder):
    script = dialogue.parse("## Act: Chapter one\n## Scene: The lamp room\nMIRA: Sleep.\nTOBI: Not yet.\n"
                            "## Act: Chapter two\n## Scene: The gallery\nMIRA: A sail.")
    characters = cast.read(folder)
    staged = dialogue.staging(script, characters, look="Muted teal and amber; 35 mm; light grain; 1970s coast.")
    listing = staged.listing
    assert ("mira (Mira): A tall woman in her thirties, short silver hair, a long green oilskin coat."
            in listing)
    assert "Speaks slowly" in listing  # the sheet's notes
    assert "Scene 1 (Chapter one; mira is 34): The lamp room" in listing
    assert "Scene 2 (Chapter two; mira is 41): The gallery" in listing
    assert "Muted teal and amber" in listing
    assert dialogue.staging(script).listing == dialogue.writer_listing(script)  # no cast, no look: as in phase 1
