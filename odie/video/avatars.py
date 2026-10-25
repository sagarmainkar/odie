"""3D characters in a dialogue video (phase 3, 25 Oct 2026): a cast sheet whose `asset:` names a .vrm or .glb file
makes that speaker appear as a 3D character, drawn on the page and moved by their line's sound, instead of as a
still picture. This module is the first step: the sheet's asset, checked, becomes a Model.

How a model gets to the page (decided here, built in later steps): its bytes travel over the tab's DevTools channel
in chunks and are put together inside the tab, never written into the HTML, so the page stays small and the sealed
rule (the page reaches no file, no network) stays as it is."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from odie.video import cast


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
