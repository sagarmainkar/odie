"""A dialogue video's cast (phase 2, 23 Oct 2026): one Markdown sheet per character in a folder of the user's own (in
the vault, or anywhere they name), read for every video of a work, so each character looks and sounds the same in all
of them. Nothing about any story is in Odie: the sheets are the user's.

A sheet (all fields optional but id):

    ---
    id: mira
    display_name: Mira
    canonical: "One frozen paragraph about how she looks; used word for word."
    voice: af_bella
    ages:
      - act: Chapter one
        age: 34
        ref: refs/mira-34.jpg
    refs: [refs/mira-front.jpg]
    asset: models/mira.glb      # read and kept for later: 3D characters aren't drawn yet
    ---
    Notes for the writer (optional).

Markdown files without front matter, or without an id, are notes and are skipped."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
PICTURE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".heic")
MAX_NOTES = 1500  # characters of a sheet's notes the writer gets
TEMPLATE_HINT = ('Each character is a Markdown file starting with front matter: "---", then "id: mira", '
                 '"canonical: …" and "voice: …" lines, then "---".')


class CastProblem(ValueError):
    """The cast folder can't be used, in words for the user."""


@dataclass
class Age:
    act: str
    age: int | None
    ref: str = ""


@dataclass
class Character:
    id: str  # lower case, as the script's speakers are
    display_name: str
    canonical: str = ""
    voice: str = ""
    ages: list[Age] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    asset: str = ""
    notes: str = ""
    folder: Path | None = None

    def age_in(self, act: str) -> int | None:
        """The character's age in an act, as the sheet gives it: "Chapter one" -> 34; an act the sheet doesn't list,
        or no act -> None."""
        for age in self.ages:
            if act and age.act.strip().lower() == act.strip().lower():
                return age.age
        return None

    def pictures(self) -> list[Path]:
        """The character's reference pictures that exist in the folder: the refs first, then each age's, each once;
        a missing file is left out."""
        named = [*self.refs, *(age.ref for age in self.ages if age.ref)]
        out = []
        for name in named:
            path = (self.folder / name) if self.folder else Path(name)
            if path.suffix.lower() in PICTURE_SUFFIXES and path.is_file() and path not in out:
                out.append(path)
        return out

    def as_data(self) -> dict:
        """The character as the job keeps it."""
        return {"id": self.id, "display_name": self.display_name, "canonical": self.canonical, "voice": self.voice,
                "ages": [age.__dict__.copy() for age in self.ages], "refs": list(self.refs), "asset": self.asset,
                "notes": self.notes, "folder": str(self.folder) if self.folder else ""}


def from_data(data: dict) -> Character:
    """A character the job kept (Character.as_data) read back."""
    folder = Path(data["folder"]) if data.get("folder") else None
    return Character(id=data["id"], display_name=data["display_name"], canonical=data.get("canonical", ""),
                     voice=data.get("voice", ""), ages=[Age(**age) for age in data.get("ages", [])],
                     refs=list(data.get("refs", [])), asset=data.get("asset", ""), notes=data.get("notes", ""),
                     folder=folder)


def text_of(value) -> str:
    """A front-matter value as one line of text: None -> ""; "  Mira " -> "Mira"; 34 -> "34"."""
    if value is None:
        return ""
    return str(value).strip()


def sheet(path: Path) -> Character | None:
    """One character from a Markdown file, or None for a note (no front matter, or no id). Front matter that isn't
    YAML raises CastProblem naming the file."""
    found = FRONT_MATTER.match(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    if found is None:
        return None
    try:
        fields = yaml.safe_load(found.group(1)) or {}
    except yaml.YAMLError as e:
        raise CastProblem(f"{path.name}: its front matter can't be read ({str(e).splitlines()[0]}).") from None
    if not isinstance(fields, dict) or not text_of(fields.get("id")):
        return None
    written_id = text_of(fields["id"])
    ages = []
    for entry in fields.get("ages") or []:
        if not isinstance(entry, dict):
            continue
        age = entry.get("age")
        if not isinstance(age, int):
            age = None  # "about forty" or nothing: no number to give the writer
        ages.append(Age(act=text_of(entry.get("act")), age=age, ref=text_of(entry.get("ref"))))
    refs = fields.get("refs") or []
    if isinstance(refs, str):
        refs = [refs]
    display_name = text_of(fields.get("display_name"))
    if not display_name:
        display_name = written_id
    return Character(id=written_id.lower(), display_name=display_name, canonical=text_of(fields.get("canonical")),
                     voice=text_of(fields.get("voice")), ages=ages,
                     refs=[text_of(ref) for ref in refs if text_of(ref)], asset=text_of(fields.get("asset")),
                     notes=found.group(2).strip()[:MAX_NOTES], folder=path.parent)


def read(folder: Path) -> list[Character]:
    """Every character sheet in the folder (its top level, by file name), notes skipped. Raises CastProblem for a
    folder with no sheets (saying how to write one), a sheet that can't be read, or two sheets for one id."""
    characters: list[Character] = []
    for path in sorted(folder.glob("*.md")):
        character = sheet(path)
        if character is None:
            continue
        if any(other.id == character.id for other in characters):
            raise CastProblem(f'Two sheets in {folder.name} are for "{character.id}": keep one.')
        characters.append(character)
    if not characters:
        raise CastProblem(f"No character sheets in {folder}. {TEMPLATE_HINT}")
    return characters


def find_folder(reference: str, vault_dir: str | None, workspace: Path | None = None) -> Path:
    """The cast folder the user named: an absolute path or one from ~, else a path in their vault, else one in Odie's
    workspace. "Stories/Lighthouse/cast" with the vault set -> <vault>/Stories/Lighthouse/cast. Raises CastProblem
    when there's no such folder."""
    given = Path(reference.strip()).expanduser()
    places = []
    if given.is_absolute():
        places.append(given)
    else:
        if vault_dir:
            places.append(Path(vault_dir).expanduser() / given)
        if workspace is not None:
            places.append(workspace / given)
    for place in places:
        if place.is_dir():
            return place
    raise CastProblem(f'No folder "{reference}" in the vault or Odie\'s workspace: give the cast folder\'s path in '
                      "the vault (Stories/My story/cast) or its full path.")
