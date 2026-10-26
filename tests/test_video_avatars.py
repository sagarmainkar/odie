"""A 3D character (phase 3): the cast sheet's asset: is checked and becomes a speaker's Model, only for the speakers
of the script being made."""
import asyncio
import base64
from contextlib import asynccontextmanager

import pytest

from odie.browser import RENDER_ARGS
from odie.browser.engine import Browser
from odie.store.db import Store
from odie.video import avatars, cast, dialogue, page
from tests.test_video_kit import BIN, needs_browser
from tests.tiny_glb import tiny_glb

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
    ("/tmp/mira.vrm", "inside the folder cast"),
    ("../mira.vrm", "inside the folder cast"),
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
    with pytest.raises(cast.CastProblem, match="inside the folder cast"):
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


# ---- Handing a model to the page (the bytes over the tab's channel, never in the HTML) ----

BODY = '<script>Video.scenes([{draw(t, s) {}}])</script>'
TIMINGS = {"starts": [0.0], "lengths": [2.0]}
LINES = [{"index": 0, "speaker": "mira", "scene": 1, "t": 0.5, "dur": 1.0, "amplitude": []}]
# The first bytes of a JPEG picture, padded: a file renamed to .glb that isn't one.
NOT_GLTF = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 300


def a_model(tmp_path, data: bytes, size: int | None = None) -> avatars.Model:
    """Mira's model as the file mira.glb holding `data` (its size as checked: len(data) unless given)."""
    path = tmp_path / "mira.glb"
    path.write_bytes(data)
    if size is None:
        size = len(data)
    return avatars.Model(speaker="mira", name="Mira", path=path, size=size)


class FakeTab:
    """A sealed tab that records what it is told and answers __avatars.ready() with `ready`."""

    def __init__(self, ready):
        self.ready = ready
        self.said = []

    async def eval(self, expression):
        self.said.append(expression)
        if expression == "__avatars.ready()":
            return self.ready
        return None


def test_no_model_no_3d_on_the_page():
    assert avatars.page_script([]) == ""
    html = page.assemble(BODY, TIMINGS, lines_script=dialogue.lines_script(LINES))
    assert html == page.assemble(BODY, TIMINGS, lines_script=dialogue.lines_script(LINES), avatar_script="")
    for word in ("GLTFLoader", "THREE_VRM", "__avatars"):
        assert word not in html


def test_a_model_brings_the_loader_and_the_list_but_not_its_bytes(tmp_path):
    model = a_model(tmp_path, b"glTF" + b"\0" * 100)
    script = avatars.page_script([model])
    assert "GLTFLoader" in script and "THREE_VRM" in script
    assert '__avatars.expect({"mira": {"name": "Mira", "kind": "glb", "bytes": 104}})' in script
    html = page.assemble(BODY, TIMINGS, avatar_script=script, lines_script=dialogue.lines_script(LINES))
    assert html.index("__avatars.expect") < html.index("<script>Video.lines(")


def test_a_name_can_never_close_the_script_it_sits_in(tmp_path):
    model = avatars.Model(speaker="mira", name="Mira</script>", path=tmp_path / "mira.vrm", size=1)
    script = avatars.page_script([model])
    assert script.count("</script>") == 4  # the three kit files' and the list's own


def test_frames_are_called_through_the_avatars_only_when_there_are_some():
    assert avatars.frame_call(1.5, False) == "__frame(1.5)"
    assert avatars.frame_call(1.5, True) == "__avatars.frame(1.5)"


def test_a_model_is_read_once_and_cut_into_4_mb_pieces(tmp_path):
    data = bytes(range(256)) * (avatars.CHUNK_BYTES // 256 * 2 + 1)  # just over two pieces
    [loaded] = avatars.load([a_model(tmp_path, data)])
    assert len(loaded.pieces) == 3
    assert b"".join(base64.b64decode(piece) for piece in loaded.pieces) == data


async def test_hand_over_sends_the_pieces_in_order_then_waits_for_the_parse(tmp_path):
    tab = FakeTab(ready={"failed": {}})
    await avatars.hand_over(tab, avatars.load([a_model(tmp_path, b"x" * 10)]))
    assert tab.said == ['__avatars.bytes("mira", 0, "eHh4eHh4eHh4eA==")', "__avatars.ready()"]


async def test_a_model_the_page_cant_parse_is_refused_naming_the_speaker(tmp_path):
    tab = FakeTab(ready={"failed": {"mira": "Unexpected token"}})
    with pytest.raises(cast.CastProblem) as e:
        await avatars.hand_over(tab, avatars.load([a_model(tmp_path, b"x")]))
    assert str(e.value) == ("Mira's 3D model (mira.glb) couldn't be read; export it again (VRoid Studio: .vrm) or "
                            "remove asset: from their sheet. The loader said: Unexpected token")


async def test_the_advice_comes_first_and_the_loaders_full_stop_is_dropped(tmp_path):
    tab = FakeTab(ready={"failed": {"mira": "it isn't a glTF binary file." + " (long)" * 60}})
    with pytest.raises(cast.CastProblem) as e:
        await avatars.hand_over(tab, avatars.load([a_model(tmp_path, b"x")]))
    assert "remove asset: from their sheet" in str(e.value)[:200]  # the job's one-line summary cuts at 200 characters
    tab = FakeTab(ready={"failed": {"mira": "it isn't a glTF binary file."}})
    with pytest.raises(cast.CastProblem) as e:
        await avatars.hand_over(tab, avatars.load([a_model(tmp_path, b"x")]))
    assert str(e.value).endswith("The loader said: it isn't a glTF binary file")


def test_a_model_deleted_after_the_check_is_refused_naming_the_speaker(folder):
    (folder / "models" / "mira.vrm").write_bytes(b"x" * 10)
    [model] = avatars.models_for(cast.read(sheet_with(folder, "models/mira.vrm")), ["mira"])
    model.path.unlink()
    with pytest.raises(cast.CastProblem) as e:
        avatars.load([model])
    message = str(e.value)
    assert message.startswith("Mira's asset (mira.vrm)")
    assert "couldn't be read" in message and "put the file back" in message
    assert message.endswith("(speaker id: mira).")


async def handed_over(model, tmp_path, before=None, after="__avatars.ready()"):
    """Opens a sealed page carrying `model`'s loader, runs the `before` expression (if any), hands the model over and
    gives back what the `after` expression returns, with the page's errors. A CastProblem from the hand-over is
    raised; the whole hand-over may take at most 10 s (a hang fails the test, it doesn't wait 120 s)."""
    html = page.assemble(BODY, TIMINGS, avatar_script=avatars.page_script([model]),
                         lines_script=dialogue.lines_script(LINES))
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            if before:
                await p.eval(before)
            await asyncio.wait_for(avatars.hand_over(p, avatars.load([model])), 10)
            value = await p.eval(after)
            errors = list(p.errors)
    finally:
        await b.close()
    return value, errors


@needs_browser
async def test_a_tiny_gltf_is_handed_to_a_sealed_tab_and_parsed(tmp_path):
    ready, errors = await handed_over(a_model(tmp_path, tiny_glb()), tmp_path)
    assert ready == {"failed": {}}
    assert errors == []


@needs_browser
async def test_the_parsed_model_is_kept_for_the_helpers_and_frames_draw_after_it(tmp_path):
    mira = "__avatars.models.get('mira')"
    after = (f"__avatars.frame(0.75).then(drawn => [drawn, __avatars.time, {mira}.kind, {mira}.vrm,"
             f" {mira}.gltf.scene.getObjectByName('Head') !== undefined])")
    value, errors = await handed_over(a_model(tmp_path, tiny_glb()), tmp_path, after=after)
    assert value == [True, 0.75, "glb", None, True]
    assert errors == []


@needs_browser
@pytest.mark.parametrize("which", ["a renamed jpeg", "a truncated download"])
async def test_a_file_that_isnt_gltf_is_refused_in_words_not_a_hang(tmp_path, which):  # jpeg, cut-off file
    data = NOT_GLTF
    if which == "a truncated download":
        data = tiny_glb()[:200]
    mira_words = r"Mira's 3D model \(mira.glb\) couldn't be read; export it again .+The loader said: .+"
    with pytest.raises(cast.CastProblem, match=mira_words) as e:
        await handed_over(a_model(tmp_path, data), tmp_path)
    if which == "a renamed jpeg":
        assert "it isn't a glTF binary file" in str(e.value)


@needs_browser
async def test_a_model_whose_bytes_didnt_all_arrive_is_refused(tmp_path):
    with pytest.raises(cast.CastProblem, match="only 100 of 150 bytes arrived"):
        await handed_over(a_model(tmp_path, b"x" * 100, size=150), tmp_path)


@needs_browser
async def test_a_parse_that_never_finishes_is_refused_after_the_page_stops_waiting(tmp_path):
    never_calls_back = "THREE.GLTFLoader.prototype.parse = function () {}; __avatars.parseSeconds = 0.3; true"
    with pytest.raises(cast.CastProblem, match="didn't finish within 0.3 s"):
        await handed_over(a_model(tmp_path, tiny_glb()), tmp_path, before=never_calls_back)


# ---- The writer's page check draws with the models ----

SCENE_COUNT = "window.__sceneCount === undefined ? null : window.__sceneCount"
SCRIPT = dialogue.parse("## Scene: A workshop\nMIRA: Still here?\n")


class CheckTab:
    """A stand-in sealed tab for the page check: a one-scene page that loaded without errors, parsed every model and
    placed no sound cues. Records every expression it is told."""

    def __init__(self):
        self.errors = []
        self.said = []

    async def eval(self, expression):
        self.said.append(expression)
        if expression == SCENE_COUNT:
            return 1
        if expression == "__avatars.ready()":
            return {"failed": {}}
        if expression == "Video.soundCues()":
            return []
        return None


class CheckBrowser:
    """A stand-in browser whose sealed page is one CheckTab; keeps the HTML it was given."""

    def __init__(self):
        self.tab = CheckTab()
        self.html = ""

    @asynccontextmanager
    async def sealed_page(self, html, width, height):
        self.html = html
        yield self.tab


async def test_the_page_check_draws_with_the_models(tmp_path):
    browser = CheckBrowser()
    staged = dialogue.staging(SCRIPT)
    model = a_model(tmp_path, b"x" * 10)
    result = await page.check_with_cues(BODY, staged.narration, browser, lines_for=staged.lines_for, models=[model])
    assert result.problem is None
    said = browser.tab.said
    assert said[:2] == ['__avatars.bytes("mira", 0, "eHh4eHh4eHh4eA==")', "__avatars.ready()"]
    probes = [expression for expression in said if "frame(" in expression]
    assert len(probes) == page.PROBES_PER_SCENE
    assert all(expression.startswith("__avatars.frame(") for expression in probes)
    assert "__avatars.expect" in browser.html


async def test_the_page_check_without_models_draws_as_before():
    browser = CheckBrowser()
    staged = dialogue.staging(SCRIPT)
    await page.check_with_cues(BODY, staged.narration, browser, lines_for=staged.lines_for)
    probes = [expression for expression in browser.tab.said if "frame(" in expression]
    assert all(expression.startswith("__frame(") for expression in probes)
    assert "__avatars" not in browser.html


async def test_a_model_the_check_cant_parse_ends_the_job_in_its_words(tmp_path, monkeypatch):
    from odie.video import writer
    from tests.test_video_writer import Context
    words = "Mira's 3D model (mira.glb) couldn't be read; export it again. The loader said: it isn't a glTF binary file"

    async def unparsed(tab, loaded):
        raise cast.CastProblem(words)

    monkeypatch.setattr(avatars, "hand_over", unparsed)
    staged = dialogue.staging(SCRIPT, models=[a_model(tmp_path, b"x" * 10)])
    desk = writer.Desk(topic="Night", pages=tmp_path / "pages", staging=staged)
    [submit] = writer.tools_for(desk, CheckBrowser())
    answer = await submit("Night", BODY, tool_context=Context())
    assert answer == {"error": words}
    assert desk.failure == words  # harness.CantCheck: not the writer's fault, so no refusal
    assert desk.rejected == 0
