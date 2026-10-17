"""Pictures and clips for an explainer video. The chat hands them over as short lines, "address — what it shows"
(make_video's images and clips); in the background, before the writer runs, Odie fetches each one (web pictures and
the user's own through odie.decks.photos.fetch, clips through the same guarded download), prepares it (a picture
upright, at most 2400 px, a JPEG; a clip its first 15 s at 720p, no sound, VP9 WebM, which every Chromium plays),
names it img1…, clip1… in the order given, and keeps it in the job's assets/ folder.

The writer never sees an address or a pixel: it reads `listing`, the names with their sizes and words. When the video
is drawn, `staple` puts every file into the page as a data URI in one `Video.assets({...})` script (video.js's
registry), so the sealed tab needs nothing from the network."""
import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from odie.agent import turn as chat_turn
from odie.decks import photos
from odie.net import DownloadError, safe_download
from odie.video.encode import EncodeError, ffmpeg, probe, run, tail

log = logging.getLogger("odie.video")

MAX_IMAGES = 20
MAX_CLIPS = 6
CLIP_SECONDS = 15                # a clip is cut to its first 15 seconds
MAX_CLIP_BYTES = 60_000_000      # the most a clip's download may be
MAX_STAPLED_MB = 60
MAX_STAPLED_BYTES = MAX_STAPLED_MB * 1024 * 1024  # every data URI in the page together
IMAGE_EDGE = 2400                # a picture's longer side at most: room to push in on a 1920 px stage
JPEG_QUALITY = 85
CLIP_BOX = "1280:720"            # a clip is fitted inside 1280×720, its shape kept
CLIP_QUALITY = "33"              # VP9's constant quality: about 2–4 MB for 15 s at 720p
STAGE = (14, 17, 23)             # #0e1117, the kit's stage: what a transparent picture sits on
DASH = "—"                       # the em dash between the address and the words ("address — words")
WEB = re.compile(r"^https?://", re.IGNORECASE)
CLIP_ADDRESS = re.compile(r"^https://", re.IGNORECASE)
OWN_PICTURE = ("photo:", "upload:", "screenshot:")
CREDIT = re.compile(r"^(.*?)\s*\(([^()]*)\)$")  # words that end in "(…)": the words, then the credit
MIME = {"image": "image/jpeg", "clip": "video/webm"}
SUFFIX = {"image": ".jpg", "clip": ".webm"}

PICTURES_HEADER = "Pictures (use by name with s.photo / s.texture; you cannot add others):"
CLIPS_HEADER = "Clips (use by name with s.clip; you cannot add others):"
DROPPED_HEADER = "Left out (don't use these names):"
# Why a fetched file couldn't be prepared, as the writer is told it (ffmpeg's and Pillow's own words carry file paths,
# so they go to the log instead).
NOT_A_CLIP = "it isn't a video Odie can read"
NOT_A_PICTURE = "it isn't a picture Odie can read"
SOMETHING_WRONG = "something went wrong (see Odie's log)"
OVER_THE_CAP = "{name} was left out: the pictures and clips before it already fill what a video can carry"


class AssetProblem(Exception):
    """Why the pictures or clips can't be used, in words the chat (or, for the staple, the user) can act on."""


@dataclass
class Given:
    """One line from the chat, read: where the picture is, what it shows, and its credit (web ones only)."""
    address: str
    words: str
    credit: str


@dataclass
class Asset:
    """One prepared picture or clip in the job's assets/ folder, under the name the writer uses."""
    name: str          # "img1", "clip1"
    kind: str          # "image" or "clip"
    words: str
    credit: str        # "" for the user's own pictures
    width: int
    height: int
    seconds: float     # a clip's length; 0.0 for a picture
    path: Path


class Dropped(Exception):
    """A picture or clip that couldn't be used: the line the writer is told ("img4 couldn't be fetched: …")."""


# Reading the chat's lines.

def lines_as_given(value, what: str) -> list[str]:
    """The lines the model meant. None -> []; a list of texts -> the same; the list sent as JSON text
    ('["photo:3F2A — us"]') -> the list; one plain text -> a list of that one line. Anything else ({"a": "b"}, 5, a
    list holding a number) -> AssetProblem."""
    not_a_list = (f'{what} is a list of short texts, each "address — what it shows": ["https://… — Red Fort at '
                  'dusk (Photo by A on Unsplash)", "photo:<id> — us at the gate, 12 May"].')
    if value is None:
        return []
    lines = value
    if isinstance(value, str):
        try:
            lines = json.loads(value)
        except ValueError:
            lines = [value]
    if not isinstance(lines, list):
        raise AssetProblem(not_a_list)
    for line in lines:
        if not isinstance(line, str):
            raise AssetProblem(not_a_list)
    return [line.strip() for line in lines]


def is_web(address: str) -> bool:
    """Decides whether an address is on the web (so it is fetched by download, refused in a private chat, and
    credited): "https://images.unsplash.com/a.jpg" -> True; "photo:3F2A", "upload:7b" -> False."""
    return bool(WEB.match(address))


def address_problem(address: str, what: str, number: int) -> str | None:
    """Decides whether Odie can fetch this address, as words to fix or None. A picture is a web address or the user's
    own (photo:, upload:, screenshot:): "photo:3F2A" -> None, "/api/photos/3F2A/thumb" -> the forms. A clip is only a
    web address over https: "https://videos.pexels.com/v.mp4" -> None, "photo:3F2A" -> "a clip is a web address"."""
    if what == "clips":
        if CLIP_ADDRESS.match(address):
            return None
        return (f"clips line {number}: a clip is a web address (https://…) that find_clips gave, not "
                f"\"{address}\".")
    if is_web(address) or address.startswith(OWN_PICTURE):
        return None
    return (f"images line {number}: the address is a web address (https://…), photo:<id>, upload:<id> or "
            f"screenshot:<id>, not \"{address}\".")


def words_and_credit(address: str, words: str) -> tuple[str, str]:
    """A web picture's credit is the "(…)" its words end with, as find_images gives it; the user's own pictures have
    none, so their parentheses stay in the words.
    "https://…", "Red Fort at dusk (Photo by A on Unsplash)" -> ("Red Fort at dusk", "Photo by A on Unsplash");
    "photo:3F2A", "us at the gate (12 May)" -> ("us at the gate (12 May)", "")."""
    if not is_web(address):
        return words, ""
    found = CREDIT.match(words)
    if found is None:
        return words, ""
    return found.group(1).strip(), found.group(2).strip()


def read_line(line: str, what: str, number: int) -> Given:
    """One "address — words" line as a Given; a line that can't be read -> AssetProblem naming it."""
    address, dash, words = line.partition(DASH)
    address = address.strip()
    words = words.strip()
    if not dash:
        raise AssetProblem(f'{what} line {number} has no " — " between the address and the words: "{line}". Write '
                           'each as "address — what it shows".')
    if not address:
        raise AssetProblem(f'{what} line {number} has no address before " — ": "{line}".')
    if not words:
        kind_word = "picture"
        if what == "clips":
            kind_word = "clip"
        raise AssetProblem(f'{what} line {number} says nothing about the {kind_word} after " — ": say what it shows.')
    problem = address_problem(address, what, number)
    if problem:
        raise AssetProblem(problem)
    words, credit = words_and_credit(address, words)
    return Given(address, words, credit)


def count_problem(count: int, what: str, most: int) -> str | None:
    """Decides whether there are few enough: 20 images -> None; 21 -> the limit, in words to act on."""
    if count <= most:
        return None
    return f"There are {count} {what}; a video takes at most {most}. Keep the ones the film needs most."


def parse(images, clips) -> tuple[list[Given], list[Given]]:
    """make_video's images and clips, read and checked: (pictures, clips) in the order given. Raises AssetProblem
    with the first problem: not a list, a line without " — ", no address or no words, an address Odie can't fetch,
    more than 20 images or 6 clips."""
    image_lines = lines_as_given(images, "images")
    clip_lines = lines_as_given(clips, "clips")
    problem = count_problem(len(image_lines), "images", MAX_IMAGES)
    if problem is None:
        problem = count_problem(len(clip_lines), "clips", MAX_CLIPS)
    if problem:
        raise AssetProblem(problem)
    pictures = [read_line(line, "images", n) for n, line in enumerate(image_lines, 1)]
    moving = [read_line(line, "clips", n) for n, line in enumerate(clip_lines, 1)]
    return pictures, moving


def brief_section(images: list[str], clips: list[str]) -> str:
    """The lines as the chat gave them, for the job's brief.md (kept for revisions; the writer reads the listing
    instead): "## Pictures", a "- " line each, then "Clips:" and theirs. Nothing given -> ""."""
    if not images and not clips:
        return ""
    pieces = ["## Pictures"]
    if images:
        pieces.append("\n".join(f"- {line}" for line in images))
    if clips:
        pieces.append("Clips:")
        pieces.append("\n".join(f"- {line}" for line in clips))
    return "\n\n".join(pieces)


# Preparing.

def prepare_image(src: Path, dest: Path) -> tuple[int, int]:
    """A picture made ready for the page: turned upright by its EXIF orientation, at most 2400 px on its longer side
    (never enlarged), RGB with any transparency laid on the stage colour, saved as a JPEG at quality 85 with no EXIF
    (no camera, no place). Returns its width and height."""
    with Image.open(src) as opened:
        img = ImageOps.exif_transpose(opened)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            ground = Image.new("RGB", img.size, STAGE)
            ground.paste(img, mask=img.getchannel("A"))
            img = ground
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((IMAGE_EDGE, IMAGE_EDGE))
        img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        return img.width, img.height


async def prepare_clip(src: Path, dest: Path) -> float:
    """A clip made ready for the page: its first 15 s, fitted inside 1280×720 with its shape kept, no sound, VP9 in
    WebM. Returns its length in seconds; ffmpeg's complaint (not a video, say) -> EncodeError."""
    command = [
        ffmpeg(), "-y", "-loglevel", "error", "-i", str(src),
        "-t", str(CLIP_SECONDS), "-an",
        "-vf", f"scale={CLIP_BOX}:force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-crf", CLIP_QUALITY, "-b:v", "0",
        "-deadline", "good", "-cpu-used", "4", "-row-mt", "1",
        str(dest),
    ]
    code, stderr = await run(command)
    if code != 0:
        raise EncodeError(tail(stderr) or f"ffmpeg exited with {code}")
    info = await probe(dest)
    return info["seconds"]


# Gathering.

async def fetch_clip(address: str) -> bytes:
    """A clip's file, downloaded as a picture is (public addresses only, at most 60 MB) and refused in a private chat
    with the deck's words."""
    if chat_turn.private_sites():  # the address could carry what the model read on a signed-in page
        raise photos.PhotoError(photos.PRIVATE_REFUSAL)
    data, _content_type = await safe_download(address, MAX_CLIP_BYTES)
    return data


def web_credit(given: Given) -> str:
    """The credit a picture shows in the video: a web picture's own credit from its line, else its site's name; the
    user's own pictures none. "https://ex.com/a.jpg — fort (Photo by A on Unsplash)" -> "Photo by A on Unsplash";
    "https://www.ex.com/a.jpg — fort" -> "ex.com"; "photo:3F2A — us" -> ""."""
    if not is_web(given.address):
        return ""
    if given.credit:
        return given.credit
    return photos.site_name(given.address)


def shared_fetch(fetches: dict[str, asyncio.Future], given: Given) -> asyncio.Future:
    """The fetch of this line's address: started by the first line that names it and shared by every later one, so an
    address given twice is fetched once (and its cached file never written twice at once). img1 and img3 both
    "https://ex.com/fort.jpg" -> one photos.fetch, both await it; img2 "photo:3F2A" -> a fetch of its own."""
    if given.address not in fetches:
        fetches[given.address] = asyncio.ensure_future(photos.fetch(given.address, given.credit))
    return fetches[given.address]


async def image_asset(name: str, given: Given, place: Path, fetching: asyncio.Future) -> Asset:
    """One picture, its fetch (`fetching`: odie.decks.photos.fetch, the cache, the guarded download, the private-chat
    refusal, the user's library) awaited and the file prepared as place/<name>.jpg. A failure -> Dropped with the
    line for the writer."""
    try:
        photo = await fetching
    except photos.PhotoError as e:
        raise Dropped(f"{name} couldn't be fetched: {e}") from None
    dest = place / f"{name}{SUFFIX['image']}"
    try:
        width, height = await asyncio.to_thread(prepare_image, photo.path, dest)
    except OSError as e:
        log.warning("picture %s from %s couldn't be prepared: %s", name, given.address, e)
        raise Dropped(f"{name} couldn't be prepared: {NOT_A_PICTURE}") from None
    return Asset(name, "image", given.words, web_credit(given), width, height, 0.0, dest)


async def clip_asset(name: str, given: Given, place: Path) -> Asset:
    """One clip downloaded and prepared as place/<name>.webm (the download itself isn't kept). A failure -> Dropped
    with the line for the writer."""
    try:
        data = await fetch_clip(given.address)
    except (photos.PhotoError, DownloadError) as e:
        raise Dropped(f"{name} couldn't be fetched: {e}") from None
    source = place / f"{name}-download"
    dest = place / f"{name}{SUFFIX['clip']}"
    source.write_bytes(data)
    try:
        seconds = await prepare_clip(source, dest)
        info = await probe(dest)
    except EncodeError as e:
        dest.unlink(missing_ok=True)
        log.warning("clip %s from %s couldn't be prepared: %s", name, given.address, e)
        raise Dropped(f"{name} couldn't be prepared: {NOT_A_CLIP}") from None
    finally:
        source.unlink(missing_ok=True)
    return Asset(name, "clip", given.words, given.credit, info["width"], info["height"], seconds, dest)


def stapled_size(asset: Asset) -> int:
    """How many characters an asset adds to the page as a data URI: its prefix plus its bytes in base64 (4 for every
    3, rounded up). A 3,000-byte JPEG -> 23 + 4,000 = 4,023."""
    size = asset.path.stat().st_size
    prefix = f"data:{MIME[asset.kind]};base64,"
    return len(prefix) + 4 * ((size + 2) // 3)


def fits(stapled_so_far: int, size: int) -> bool:
    """Decides whether one more asset still fits in the page: 50 MB so far and a 4 MB clip -> True; 58 MB so far and a
    4 MB clip -> False (over the 60 MB)."""
    return stapled_so_far + size <= MAX_STAPLED_BYTES


async def gather(images: list[Given], clips: list[Given], folder: Path) -> tuple[list[Asset], list[str]]:
    """Every picture and clip fetched and prepared at once into folder/assets/, named img1…, clip1… by its place in
    the order given (a dropped img2 leaves a gap, so the names the writer is told stay true). Returns the assets that
    worked, pictures then clips, and a line for each one that didn't: "img2 couldn't be fetched: The link answered
    404." Anything that would take the page over 60 MB is left out the same way, and so is one that fails in a way
    nobody foresaw (logged): a single bad file never fails the video."""
    place = folder / "assets"
    place.mkdir(parents=True, exist_ok=True)
    fetches: dict[str, asyncio.Future] = {}
    names = []
    work = []
    for number, given in enumerate(images, 1):
        name = f"img{number}"
        names.append(name)
        work.append(image_asset(name, given, place, shared_fetch(fetches, given)))
    for number, given in enumerate(clips, 1):
        name = f"clip{number}"
        names.append(name)
        work.append(clip_asset(name, given, place))
    results = await asyncio.gather(*work, return_exceptions=True)

    gathered = []
    dropped = []
    stapled_so_far = 0
    for name, result in zip(names, results):
        if isinstance(result, Dropped):
            dropped.append(str(result))
            continue
        if isinstance(result, Exception):
            # Anything else that went wrong with one file is that file's problem only: the video goes on without it.
            log.error("%s couldn't be used", name, exc_info=result)
            dropped.append(f"{name} couldn't be used: {SOMETHING_WRONG}")
            continue
        if isinstance(result, BaseException):
            raise result  # cancelled (Odie stopping): not one file's problem
        size = stapled_size(result)
        if not fits(stapled_so_far, size):
            result.path.unlink(missing_ok=True)
            dropped.append(OVER_THE_CAP.format(name=result.name))
            continue
        stapled_so_far += size
        gathered.append(result)
    return gathered, dropped


# What the writer reads; what the job keeps; what the page carries.

def orientation(width: int, height: int) -> str:
    """The picture's shape in a word: 1920×1280 -> "landscape"; 1200×1600 -> "portrait"; 800×800 -> "square"."""
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def columns(rows: list[list[str]]) -> list[str]:
    """Rows of cells lined up in columns, two spaces apart, each line indented by two; the last cell isn't padded.
    [["img1", "a"], ["img10", "b"]] -> ["  img1   a", "  img10  b"]."""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    lines = []
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row, widths)]
        cells.append(row[-1])
        lines.append("  " + "  ".join(cells))
    return lines


def listing(assets: list[Asset], dropped: list[str]) -> str:
    """The block the writer's prompt carries: the pictures (name, size, shape, words), the clips (the same and their
    length), then what was left out, each under its header. No assets and nothing dropped -> ""."""
    pictures = []
    clips = []
    for asset in assets:
        size = f"{asset.width}×{asset.height}"
        shape = orientation(asset.width, asset.height)
        if asset.kind == "clip":
            clips.append([asset.name, size, shape, f"{round(asset.seconds)} s", asset.words])
        else:
            pictures.append([asset.name, size, shape, asset.words])
    blocks = []
    if pictures:
        blocks.append("\n".join([PICTURES_HEADER, *columns(pictures)]))
    if clips:
        blocks.append("\n".join([CLIPS_HEADER, *columns(clips)]))
    if dropped:
        blocks.append("\n".join([DROPPED_HEADER, *[f"  {line}" for line in dropped]]))
    return "\n".join(blocks)


def credits(assets: list[Asset]) -> list[str]:
    """The credits the video must show, in order, each once: the web pictures' and clips' (the user's own carry
    none). ["Photo by A on Unsplash", "", "Photo by A on Unsplash", "Pexels, by B"] -> the first and the last."""
    shown = []
    for asset in assets:
        if asset.credit and asset.credit not in shown:
            shown.append(asset.credit)
    return shown


def as_record(asset: Asset) -> dict:
    """An asset as job.data keeps it: everything but the data, the file named within the assets folder."""
    return {"name": asset.name, "kind": asset.kind, "words": asset.words, "credit": asset.credit,
            "width": asset.width, "height": asset.height, "seconds": asset.seconds, "file": asset.path.name}


def from_records(records: list[dict], place: Path) -> list[Asset]:
    """The assets back from job.data's records, their files in `place` (the job's assets folder)."""
    assets = []
    for r in records:
        assets.append(Asset(r["name"], r["kind"], r["words"], r["credit"], r["width"], r["height"], r["seconds"],
                            place / r["file"]))
    return assets


def data_uri(asset: Asset) -> str:
    encoded = base64.b64encode(asset.path.read_bytes()).decode("ascii")
    return f"data:{MIME[asset.kind]};base64,{encoded}"


def staple(assets: list[Asset]) -> str:
    """The script that gives the page its pictures and clips, for page.assemble to put after the kit:
    <script>Video.assets({"img1": {"kind": "image", "src": "data:image/jpeg;base64,…", "width": 2400, "height": 1600},
    "clip1": {"kind": "clip", "src": "data:video/webm;base64,…", "width": 1280, "height": 720, "seconds": 15.0}})
    </script>. No assets -> "". Over 60 MB in all -> AssetProblem (gather leaves out what wouldn't fit, so this
    guards the cap rather than trips)."""
    if not assets:
        return ""
    total = sum(stapled_size(asset) for asset in assets)
    if total > MAX_STAPLED_BYTES:
        megabytes = round(total / (1024 * 1024))
        raise AssetProblem(f"the pictures and clips come to {megabytes} MB, over the {MAX_STAPLED_MB} MB a video can "
                           "carry")
    registry = {}
    for asset in assets:
        entry = {"kind": asset.kind, "src": data_uri(asset), "width": asset.width, "height": asset.height}
        if asset.kind == "clip":
            entry["seconds"] = asset.seconds
        registry[asset.name] = entry
    return f"<script>Video.assets({json.dumps(registry)})</script>"
