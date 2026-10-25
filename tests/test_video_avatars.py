"""A 3D character (phase 3): the cast sheet's asset: is checked and becomes a speaker's Model, only for the speakers
of the script being made."""
import pytest

from odie.store.db import Store
from odie.video import avatars, cast

MIRA = """---
id: mira
display_name: Mira
asset: models/mira.vrm
---
"""

TOBI = """---
id: tobi
display_name: Tobi
---
"""


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "cast"
    (root / "models").mkdir(parents=True)
    (root / "mira.md").write_text(MIRA)
    (root / "tobi.md").write_text(TOBI)
    return root


def sheet_with(folder, asset):
    """The folder with Mira's sheet naming `asset`."""
    (folder / "mira.md").write_text(MIRA.replace("models/mira.vrm", asset))
    return folder


def test_a_speakers_model_inside_the_folder_becomes_a_model(folder):
    (folder / "models" / "mira.vrm").write_bytes(b"x" * 10)
    [model] = avatars.models_for(cast.read(folder), ["mira", "tobi"])
    assert (model.speaker, model.name, model.size, model.kind) == ("mira", "Mira", 10, "vrm")
    assert model.path == (folder / "models" / "mira.vrm").resolve()


def test_upper_case_suffixes_are_fine(folder):
    (folder / "models" / "Mira.VRM").write_bytes(b"x")
    [model] = avatars.models_for(cast.read(sheet_with(folder, "models/Mira.VRM")), ["mira"])
    assert model.kind == "vrm"


def test_a_glb_is_a_glb(folder):
    (folder / "models" / "mira.glb").write_bytes(b"x")
    [model] = avatars.models_for(cast.read(sheet_with(folder, "models/mira.glb")), ["mira"])
    assert model.kind == "glb"


@pytest.mark.parametrize("asset, words", [
    ("/tmp/mira.vrm", "inside the cast folder"),
    ("../mira.vrm", "inside the cast folder"),
    ("models/mira.fbx", "a .vrm or .glb"),
    ("models/gone.vrm", "isn't in"),
])
def test_a_bad_asset_is_refused_naming_the_speaker(folder, asset, words):
    with pytest.raises(cast.CastProblem) as e:
        avatars.models_for(cast.read(sheet_with(folder, asset)), ["mira"])
    message = str(e.value)
    assert message.startswith(f"Mira's asset ({asset})")
    assert words in message
    assert message.endswith("(speaker id: mira).")


def test_a_link_out_of_the_folder_is_refused(folder, tmp_path):
    outside = tmp_path / "outside.vrm"
    outside.write_bytes(b"x")
    (folder / "models" / "mira.vrm").symlink_to(outside)
    with pytest.raises(cast.CastProblem, match="inside the cast folder"):
        avatars.models_for(cast.read(folder), ["mira"])


def test_the_size_cap_is_40_mb(folder):
    model_file = folder / "models" / "mira.vrm"
    with model_file.open("wb") as f:
        f.truncate(cast.MAX_MODEL_BYTES)  # a sparse file: nothing like 40 MB is written to disk
    [model] = avatars.models_for(cast.read(folder), ["mira"])
    assert model.size == cast.MAX_MODEL_BYTES
    with model_file.open("wb") as f:
        f.truncate(cast.MAX_MODEL_BYTES + 1)
    with pytest.raises(cast.CastProblem, match="40 MB"):
        avatars.models_for(cast.read(folder), ["mira"])


def test_a_character_who_doesnt_speak_here_is_never_checked(folder):
    (folder / "models" / "mira.vrm").write_bytes(b"x")
    (folder / "tobi.md").write_text(TOBI.replace("display_name: Tobi", "display_name: Tobi\nasset: models/missing.vrm"))
    [model] = avatars.models_for(cast.read(folder), ["mira"])
    assert model.speaker == "mira"


def test_no_assets_no_models(folder):
    (folder / "mira.md").write_text(MIRA.replace("asset: models/mira.vrm\n", ""))
    assert avatars.models_for(cast.read(folder), ["mira", "tobi"]) == []


def test_models_come_sorted_by_speaker(folder):
    (folder / "models" / "mira.vrm").write_bytes(b"x")
    (folder / "models" / "tobi.glb").write_bytes(b"y")
    (folder / "tobi.md").write_text(TOBI.replace("display_name: Tobi", "display_name: Tobi\nasset: models/tobi.glb"))
    models = avatars.models_for(cast.read(folder), ["tobi", "mira"])
    assert [model.speaker for model in models] == ["mira", "tobi"]


def test_a_character_with_an_asset_and_no_folder_is_refused():
    lone = cast.Character(id="mira", display_name="Mira", asset="models/mira.vrm")
    with pytest.raises(cast.CastProblem, match="has no cast folder"):
        avatars.models_for([lone], ["mira"])


def test_the_video_is_refused_when_asked_for_with_a_missing_model(isolated_settings, tmp_path):
    from odie.agent.tools.files import workspace
    from tests.test_video_tool import tools
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    place = workspace() / "night-cast"
    place.mkdir(parents=True, exist_ok=True)
    (place / "mira.md").write_text(MIRA.replace("models/mira.vrm", "models/gone.vrm"))
    (workspace() / "night.md").write_text("## Scene: A workshop\nMIRA: Still here?\n")
    with pytest.raises(cast.CastProblem, match="Mira's asset"):
        tools.dialogue_as_given("night.md", None, store, cast_reference="night-cast")
