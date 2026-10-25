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
    asset: models/mira.vrm   # a 3D model (.vrm or .glb, at most 40 MB) inside the folder
    ---
    Notes for the writer (optional).

Markdown files without front matter, or without an id, are notes and are skipped. A cast folder must be in the
user's vault or Odie's workspace, and a sheet's pictures and 3D model must be inside its folder."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
PICTURE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")  # what Odie can read (HEIC: export it as a JPEG)
MODEL_SUFFIXES = (".vrm", ".glb")  # a 3D character (VRoid Studio exports .vrm)
MAX_MODEL_MB = 40
MAX_MODEL_BYTES = MAX_MODEL_MB * 1024 * 1024
MAX_NOTES = 1500  # characters of a sheet's notes the writer gets
MAX_CANONICAL = 1500  # characters of a sheet's description the writer gets
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
        """The character's reference pictures that exist in the folder: the refs first, then each age's, each once.
        A missing file, one that isn't a picture, or one outside the folder (an absolute path, ../, a link out) is
        left out: refs: [refs/front.jpg, /Users/x/a.jpg, ../b.jpg] -> [<folder>/refs/front.jpg]."""
        if self.folder is None:
            return []
        home = self.folder.resolve()
        named = [*self.refs, *(age.ref for age in self.ages if age.ref)]
        out = []
        for name in named:
            if Path(name).is_absolute():
                continue
            path = (self.folder / name).resolve()
            inside = path.is_relative_to(home)
            if inside and path.suffix.lower() in PICTURE_SUFFIXES and path.is_file() and path not in out:
                out.append(path)
        return out

    def model_file(self) -> Path | None:
        """The character's 3D model, checked: no asset: on the sheet -> None; models/mira.vrm that is a file in the
        folder, a .vrm or .glb (any case) of at most 40 MB -> its resolved path. Anything else raises CastProblem,
        naming the character and the asset: /tmp/mira.vrm or ../mira.vrm or a link out of the folder -> "must be
        inside the cast folder"; models/mira.fbx -> "a 3D character is a .vrm or .glb file"; models/gone.vrm ->
        "isn't in cast"; a 41 MB file -> "a 3D character can be at most 40 MB"; an asset on a character with no
        folder -> "has no cast folder"."""
        if not self.asset:
            return None
        start = f"{self.display_name}'s asset ({self.asset})"
        who = f"(speaker id: {self.id})."
        if self.folder is None:
            raise CastProblem(f"{start} has no cast folder {who}")
        home = self.folder.resolve()
        path = (self.folder / self.asset).resolve()
        if Path(self.asset).is_absolute() or not path.is_relative_to(home):
            raise CastProblem(f"{start} must be inside the cast folder {self.folder.name} {who}")
        suffix = path.suffix.lower()
        if suffix not in MODEL_SUFFIXES:
            named = suffix or "file with no ending"
            raise CastProblem(f"{start} is a {named}; a 3D character is a .vrm or .glb file (VRoid Studio exports "
                              f".vrm) {who}")
        if not path.is_file():
            raise CastProblem(f"{start} isn't in {self.folder.name}: put the file there or remove asset: from the "
                              f"sheet {who}")
        size = path.stat().st_size
        if size > MAX_MODEL_BYTES:
            megabytes = size / (1024 * 1024)
            raise CastProblem(f"{start} is {megabytes:.1f} MB; a 3D character can be at most {MAX_MODEL_MB} MB "
                              f"(VRoid Studio's export can shrink its textures) {who}")
        return path

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


def text_of(value, path: Path, name: str) -> str:
    """A front-matter value as one line of text: None -> ""; "  Mira " -> "Mira"; 34 -> "34"; a list, a mapping or
    true/false -> CastProblem naming the file and the field ("anna.md: canonical is one line of text …")."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise CastProblem(f"{path.name}: {name} is one line of text, not {type(value).__name__}.")
    return str(value).strip()


def age_of(value) -> int | None:
    """An age as people write it: 34 or "34" -> 34; true, "about forty" or nothing -> None (no number to give)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def listed(value, path: Path, name: str) -> list:
    """A field that is a list ("refs", "ages"), as a list: None -> []; one text -> [it]; a list -> itself; anything
    else -> CastProblem naming the file ("anna.md: refs is a list …")."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    raise CastProblem(f"{path.name}: {name} is a list, like [refs/front.jpg].")


def sheet(path: Path) -> Character | None:
    """One character from a Markdown file, or None for a note (no front matter, or no id): "---\nid: Mira\nvoice:
    af_bella\n---\nCalm." -> Mira, af_bella, notes "Calm."; "# Notes" -> None. A file that can't be read (not UTF-8),
    front matter that isn't YAML, or a field of the wrong kind raises CastProblem naming the file."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise CastProblem(f"{path.name} can't be read ({type(e).__name__}): save it as UTF-8 text.") from None
    found = FRONT_MATTER.match(text.replace("\r\n", "\n"))
    if found is None:
        return None
    try:
        fields = yaml.safe_load(found.group(1)) or {}
    except yaml.YAMLError as e:
        raise CastProblem(f"{path.name}: its front matter can't be read ({str(e).splitlines()[0]}).") from None
    if not isinstance(fields, dict) or fields.get("id") is None:
        return None
    written_id = text_of(fields["id"], path, "id")
    if not written_id:
        return None
    ages = []
    for entry in listed(fields.get("ages"), path, "ages"):
        if not isinstance(entry, dict):
            continue
        ages.append(Age(act=text_of(entry.get("act"), path, "act"), age=age_of(entry.get("age")),
                        ref=text_of(entry.get("ref"), path, "ref")))
    refs = []
    for ref in listed(fields.get("refs"), path, "refs"):
        text = text_of(ref, path, "refs")
        if text:
            refs.append(text)
    display_name = text_of(fields.get("display_name"), path, "display_name")
    if not display_name:
        display_name = written_id
    canonical = text_of(fields.get("canonical"), path, "canonical")[:MAX_CANONICAL]
    return Character(id=written_id.lower(), display_name=display_name, canonical=canonical,
                     voice=text_of(fields.get("voice"), path, "voice"), ages=ages, refs=refs,
                     asset=text_of(fields.get("asset"), path, "asset"), notes=found.group(2).strip()[:MAX_NOTES],
                     folder=path.parent)


def read(folder: Path) -> list[Character]:
    """Every character sheet in the folder (its top level, by file name), notes skipped. Raises CastProblem for a
    folder with no sheets (saying how to write one), a sheet that can't be read, or two sheets for one id."""
    characters: list[Character] = []
    for path in sorted(folder.glob("*.md")):
        if not path.is_file():
            continue
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
    """The cast folder the user named, which must be in their vault or Odie's workspace (it is read for the writer and
    stills are written into it): a path in the vault ("Stories/Lighthouse/cast"), one in the workspace, or a full
    path inside either. Raises CastProblem when there's no such folder, or it is elsewhere."""
    allowed = []
    if vault_dir:
        allowed.append(Path(vault_dir).expanduser().resolve())
    if workspace is not None:
        allowed.append(workspace.resolve())
    try:
        given = Path(reference.strip()).expanduser()
    except RuntimeError:
        raise CastProblem(f'"{reference}" isn\'t a path Odie can follow.') from None
    if given.is_absolute():
        places = [given.resolve()]
    else:
        places = [(root / given).resolve() for root in allowed]
    for place in places:
        if not any(place.is_relative_to(root) for root in allowed):
            continue
        if place.is_dir():
            return place
    if given.is_absolute() and not any(places[0].is_relative_to(root) for root in allowed):
        raise CastProblem(f"{reference} isn't in your vault or Odie's workspace: keep the cast folder there.")
    if not vault_dir:
        raise CastProblem(f'No folder "{reference}" in Odie\'s workspace (no vault is set up in Settings).')
    raise CastProblem(f'No folder "{reference}" in the vault or Odie\'s workspace: give the cast folder\'s path in '
                      "the vault (Stories/My story/cast).")
