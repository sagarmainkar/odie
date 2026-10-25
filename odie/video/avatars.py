"""3D characters in a dialogue video (phase 3, 25 Oct 2026): a cast sheet whose `asset:` names a .vrm or .glb file
makes that speaker appear as a 3D character, drawn on the page and moved by their line's sound, instead of as a
still picture. This module is the first step: the sheet's asset, checked, becomes a Model.

How a model gets to the page (decided here, built in later steps): its bytes travel over the tab's DevTools channel
in chunks and are put together inside the tab, never written into the HTML, so the page stays small and the sealed
rule (the page reaches no file, no network) stays as it is."""
from __future__ import annotations

import base64
import functools
import json
from dataclasses import dataclass
from pathlib import Path

from odie.video import cast

KIT = Path(__file__).parent / "kit"
CHUNK_BYTES = 4 * 1024 * 1024  # raw bytes of a model handed to the page in one eval (base64 makes it about 5.6 MB)


@dataclass(frozen=True)
class Model:
    """One speaker's 3D character: whose it is (the id as the script writes it), the name shown to the user, the
    checked file, and its size in bytes."""
    speaker: str
    name: str
    path: Path
    size: int

    @property
    def kind(self) -> str:
        """What sort of file it is, from its suffix: mira.vrm or Mira.VRM -> "vrm"; mira.glb -> "glb"."""
        return self.path.suffix.lower().lstrip(".")


def models_for(characters: list[cast.Character], speakers: list[str]) -> list[Model]:
    """The 3D models of the speakers of this script, sorted by speaker: characters Mira (asset: models/mira.vrm) and
    Tobi (no asset) with speakers ["mira", "tobi"] -> [Mira's model]. A character who doesn't speak here is never
    looked at, even with a broken asset:. Raises cast.CastProblem for a speaker whose asset is refused."""
    models = []
    for character in characters:
        if character.id not in speakers:
            continue
        path = character.model_file()
        if path is None:
            continue
        models.append(Model(speaker=character.id, name=character.display_name, path=path, size=path.stat().st_size))
    return sorted(models, key=lambda model: model.speaker)


@dataclass
class Loaded:
    """A model read and ready to hand to a page: the base64 text of each CHUNK_BYTES slice of its file, in order.
    Read once per render and shared by all its tabs."""
    model: Model
    pieces: list[str]


def load(models: list[Model]) -> list[Loaded]:
    """Each model's file read once and cut into CHUNK_BYTES pieces, each as base64 text: a 9 MB file -> 3 pieces
    (4 MB, 4 MB, 1 MB)."""
    loaded = []
    for model in models:
        data = model.path.read_bytes()
        pieces = []
        for offset in range(0, len(data), CHUNK_BYTES):
            piece = data[offset:offset + CHUNK_BYTES]
            pieces.append(base64.b64encode(piece).decode("ascii"))
        loaded.append(Loaded(model=model, pieces=pieces))
    return loaded


@functools.cache
def _kit() -> str:
    """The 3D kit's three files as page scripts, read once: three.js's GLTFLoader, three-vrm, and avatar.js (Odie's
    own: it takes the model's bytes and parses them). All three need three.min.js, which every page has before them."""
    scripts = []
    for name in ("gltf-loader.js", "three-vrm.min.js", "avatar.js"):
        scripts.append(f"<script>{(KIT / name).read_text()}</script>")
    return "\n".join(scripts)


def page_script(models: list[Model]) -> str:
    """Decides whether a page carries 3D code, and gives it: no models -> "" (the page is exactly as it was before
    3D characters); Mira's 104-byte mira.glb -> the kit's three scripts and then
    '<script>__avatars.expect({"mira": {"name": "Mira", "kind": "glb", "bytes": 104}})</script>', the list of models
    the page waits for. Never the models' bytes: those come later, through hand_over. A "</" in a name is written
    "<\\/", the same string to JavaScript, so a name can never close the script."""
    if not models:
        return ""
    expected = {}
    for model in models:
        expected[model.speaker] = {"name": model.name, "kind": model.kind, "bytes": model.size}
    listed = json.dumps(expected).replace("</", "<\\/")
    return _kit() + f"\n<script>__avatars.expect({listed})</script>"


def frame_call(seconds: float, with_avatars: bool) -> str:
    """Decides how a frame is asked for: a page without 3D characters as always, frame 1.5 -> "__frame(1.5)"; a page
    with them through avatar.js, which waits for the models first and keeps the frame's time for them ->
    "__avatars.frame(1.5)"."""
    if with_avatars:
        return f"__avatars.frame({seconds})"
    return f"__frame({seconds})"


async def hand_over(tab, loaded: list[Loaded]) -> None:
    """Gives each model's bytes to a sealed tab, piece by piece at its place in the file, then waits until the page
    has parsed them all. A model the page couldn't parse (not a real glTF, a truncated download) raises
    cast.CastProblem naming the speaker and the file, for the first such model; the page never waits forever (see
    avatar.js), so neither does this."""
    for one in loaded:
        speaker = json.dumps(one.model.speaker)
        for i, piece in enumerate(one.pieces):
            offset = i * CHUNK_BYTES
            await tab.eval(f'__avatars.bytes({speaker}, {offset}, "{piece}")')
    result = await tab.eval("__avatars.ready()")
    failed = result["failed"]
    for one in loaded:
        error = failed.get(one.model.speaker)
        if error is None:
            continue
        model = one.model
        raise cast.CastProblem(f"{model.name}'s 3D model ({model.path.name}) couldn't be read: {error}. Export it "
                               "again (VRoid Studio: .vrm), or remove asset: from their sheet.")
