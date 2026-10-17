"""Pictures and clips for an explainer video (odie.video.assets): the chat's "address — words" lines read and checked,
each picture fetched and prepared (upright, at most 2400 px, a JPEG), each clip cut to its first 15 s at 720p with no
sound (VP9 WebM, real ffmpeg), named img1…/clip1… in the order given, listed for the writer in words, and stapled
into the page as data URIs under a cap."""
import base64
import io
import json

import pytest
from PIL import Image

from odie.agent import turn as chat_turn
from odie.decks.photos import Photo, PhotoError
from odie.net import DownloadError
from odie.video import assets, encode

RED = (220, 30, 30)
BLUE = (30, 30, 220)


# Reading the lines.

def test_lines_are_read_as_address_words_and_a_web_credit():
    images, clips = assets.parse(
        ["https://images.unsplash.com/a.jpg — Red Fort, Delhi, at dusk (Photo by A on Unsplash)",
         "photo:3F2A — Nathula pass, us at the gate (12 May 2026)",
         "  upload:7b —  the user's itinerary sketch  "],
        ["https://videos.pexels.com/v.mp4 — waves on a Goa beach, slow (Pexels, by B)"])
    assert images == [
        assets.Given("https://images.unsplash.com/a.jpg", "Red Fort, Delhi, at dusk", "Photo by A on Unsplash"),
        assets.Given("photo:3F2A", "Nathula pass, us at the gate (12 May 2026)", ""),  # the user's own: no credit
        assets.Given("upload:7b", "the user's itinerary sketch", ""),
    ]
    assert clips == [assets.Given("https://videos.pexels.com/v.mp4", "waves on a Goa beach, slow", "Pexels, by B")]


def test_a_web_line_without_a_credit_has_none_and_words_may_hold_a_dash():
    [given], [] = assets.parse(["https://ex.com/a.jpg — Akbar — the young emperor"], None)
    assert given == assets.Given("https://ex.com/a.jpg", "Akbar — the young emperor", "")


@pytest.mark.parametrize("empty", [None, [], "[]"])
def test_nothing_given_is_no_pictures(empty):
    assert assets.parse(empty, empty) == ([], [])


def test_a_list_sent_as_json_text_is_read_as_the_list():
    images, _ = assets.parse('["photo:3F2A — us at the gate"]', None)
    assert images == [assets.Given("photo:3F2A", "us at the gate", "")]


@pytest.mark.parametrize("value", [{"a": "b"}, 5, ["photo:3F2A — us", 7]])
def test_anything_but_a_list_of_texts_is_refused(value):
    with pytest.raises(assets.AssetProblem, match="images is a list of short texts"):
        assets.parse(value, None)


def test_a_line_without_the_dash_is_refused_naming_the_line():
    with pytest.raises(assets.AssetProblem) as e:
        assets.parse(["photo:3F2A — us", "https://ex.com/a.jpg - Akbar"], None)
    words = str(e.value)
    assert "images line 2" in words and '" — "' in words and "https://ex.com/a.jpg - Akbar" in words


def test_a_blank_address_or_blank_words_are_refused():
    with pytest.raises(assets.AssetProblem, match="images line 1 has no address"):
        assets.parse(["  — Akbar"], None)
    with pytest.raises(assets.AssetProblem, match="clips line 1 says nothing about the clip"):
        assets.parse(None, ["https://ex.com/v.mp4 —   "])


def test_an_address_odie_cant_fetch_is_refused():
    with pytest.raises(assets.AssetProblem, match="images line 1.*https://.*photo:<id>.*upload:<id>.*screenshot:<id>"):
        assets.parse(["/api/photos/3F2A/thumb — us"], None)
    with pytest.raises(assets.AssetProblem, match="clips line 1.*a clip is a web address"):
        assets.parse(None, ["photo:3F2A — us"])


def test_more_than_twenty_images_or_six_clips_are_refused_with_the_limit():
    with pytest.raises(assets.AssetProblem) as e:
        assets.parse([f"photo:{i} — picture {i}" for i in range(21)], None)
    assert "21 images" in str(e.value) and "at most 20" in str(e.value)
    with pytest.raises(assets.AssetProblem) as e:
        assets.parse(None, [f"https://ex.com/{i}.mp4 — clip {i}" for i in range(7)])
    assert "7 clips" in str(e.value) and "at most 6" in str(e.value)
    assert len(assets.parse([f"photo:{i} — p" for i in range(20)], [f"https://e.x/{i} — c" for i in range(6)])[0]) == 20


# Preparing a picture.

def sideways_jpeg(path, w=3000, h=2000):
    """A picture stored on its side: the left half red, the right half blue, with EXIF orientation 6 (turn it 90°
    clockwise to view), so upright it is portrait, red at the top and blue at the bottom."""
    img = Image.new("RGB", (w, h), BLUE)
    img.paste(RED, (0, 0, w // 2, h))
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "SecretCam"
    img.save(path, "JPEG", exif=exif.tobytes())
    return path


def test_a_picture_is_turned_upright_capped_at_2400_px_and_a_plain_jpeg(tmp_path):
    dest = tmp_path / "img1.jpg"
    width, height = assets.prepare_image(sideways_jpeg(tmp_path / "side.jpg"), dest)
    assert (width, height) == (1600, 2400)
    with Image.open(dest) as img:
        assert img.format == "JPEG" and img.mode == "RGB" and img.size == (1600, 2400)
        assert len(img.getexif()) == 0  # nothing carried over: no orientation, no camera, no place
        top = img.getpixel((800, 200))
        bottom = img.getpixel((800, 2200))
    assert top[0] > 180 and top[2] < 80
    assert bottom[2] > 180 and bottom[0] < 80


def test_a_small_picture_isnt_enlarged_and_transparency_sits_on_the_stage_colour(tmp_path):
    src = tmp_path / "logo.png"
    Image.new("RGBA", (400, 300), (0, 0, 0, 0)).save(src)
    dest = tmp_path / "img2.jpg"
    assert assets.prepare_image(src, dest) == (400, 300)
    with Image.open(dest) as img:
        r, g, b = img.getpixel((200, 150))
    assert abs(r - 14) <= 3 and abs(g - 17) <= 3 and abs(b - 23) <= 3  # #0e1117, the stage


# Preparing a clip (real ffmpeg).

async def make_clip(path, seconds, size="1920x1080"):
    """A test clip with a picture and a sound, made by ffmpeg."""
    command = [encode.ffmpeg(), "-y", "-loglevel", "error",
               "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25",
               "-f", "lavfi", "-i", "sine=frequency=440",
               "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
               str(path)]
    code, stderr = await encode.run(command)
    assert code == 0, stderr
    return path



async def test_a_clip_becomes_720p_vp9_without_sound(tmp_path):
    src = await make_clip(tmp_path / "beach.mp4", 3)
    dest = tmp_path / "clip1.webm"
    seconds = await assets.prepare_clip(src, dest)
    info = await encode.probe(dest)
    assert 2.8 <= seconds <= 3.05 and abs(info["seconds"] - seconds) < 0.01
    assert info["video"] and not info["audio"]
    assert (info["width"], info["height"]) == (1280, 720)
    assert dest.read_bytes()[:4] == b"\x1a\x45\xdf\xa3"  # a WebM (Matroska) file


async def test_a_long_clip_is_cut_to_its_first_15_seconds_and_keeps_its_shape(tmp_path):
    src = await make_clip(tmp_path / "long.mp4", 17, size="320x240")
    dest = tmp_path / "clip1.webm"
    seconds = await assets.prepare_clip(src, dest)
    info = await encode.probe(dest)
    assert 14.9 <= seconds <= 15.05
    assert (info["width"], info["height"]) == (960, 720)  # 4:3 kept, fitted inside 1280×720


async def test_busy_footage_is_held_to_the_clips_bitrate(tmp_path):
    # Fresh noise in every frame is the most a clip can hold (rain, snow and surf are milder): at VP9's quality 33
    # alone, 3 s of it came to 30 MB and 15 s to 100 MB. Held to 2 Mb/s a 15 s clip stays under about 5 MB, so 3 s
    # stays under a fifth of that.
    src = tmp_path / "noise.mp4"
    command = [encode.ffmpeg(), "-y", "-loglevel", "error",
               "-f", "lavfi", "-i", "nullsrc=size=640x360:rate=25,geq=random(1)*255:128:128",
               "-t", "3", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-pix_fmt", "yuv420p", str(src)]
    code, stderr = await encode.run(command)
    assert code == 0, stderr
    dest = tmp_path / "clip1.webm"
    seconds = await assets.prepare_clip(src, dest)
    assert 2.8 <= seconds <= 3.05  # still the whole clip, however busy
    assert dest.stat().st_size < 5_000_000 * 3 / 15


async def test_a_file_that_isnt_a_video_is_an_encode_error(tmp_path):
    src = tmp_path / "page.mp4"
    src.write_text("<html>not a video</html>")
    with pytest.raises(encode.EncodeError):
        await assets.prepare_clip(src, tmp_path / "clip1.webm")


# Gathering: fetched, prepared and named in the order given; what fails is said in a line for the writer.

def jpeg_file(path, w, h, colour=RED):
    Image.new("RGB", (w, h), colour).save(path, "JPEG")
    return path


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """photos.fetch and the clip download answered by tables; a missing address fails as the real ones do."""
    pictures = {}
    clip_bytes = {}

    async def stand_in_fetch(ref, credit="", referer=None):
        if ref not in pictures:
            raise PhotoError("The link answered 404.")
        path, site = pictures[ref]
        with Image.open(path) as img:
            size = img.size
        return Photo(ref, path, size[0], size[1], credit.strip() or site)

    async def stand_in_download(url, max_bytes, referer=None, timeout=30):
        if url not in clip_bytes:
            raise DownloadError("The link answered 404.")
        return clip_bytes[url], "video/mp4"

    monkeypatch.setattr(assets.photos, "fetch", stand_in_fetch)
    monkeypatch.setattr(assets, "safe_download", stand_in_download)
    return pictures, clip_bytes


async def test_gather_names_in_order_and_says_what_was_dropped(tmp_path, sources):
    pictures, clip_bytes = sources
    pictures["https://ex.com/fort.jpg"] = (jpeg_file(tmp_path / "fort.jpg", 1920, 1280), "ex.com")
    pictures["photo:3F2A"] = (jpeg_file(tmp_path / "gate.jpg", 1200, 1600), "")
    clip_bytes["https://ex.com/waves.mp4"] = (await make_clip(tmp_path / "waves.mp4", 2, size="640x360")).read_bytes()
    images, clips = assets.parse(
        ["https://ex.com/fort.jpg — Red Fort at dusk", "https://ex.com/gone.jpg — Akbar (Photo by A on Unsplash)",
         "photo:3F2A — us at the gate"],
        ["https://ex.com/waves.mp4 — waves, slow (Pexels, by B)"])
    folder = tmp_path / "job"

    got, dropped = await assets.gather(images, clips, folder)

    assert [a.name for a in got] == ["img1", "img3", "clip1"]  # img2 keeps its number: the writer is told about it
    assert dropped == ["img2 couldn't be fetched: The link answered 404."]
    fort, gate, waves = got
    assert (fort.kind, fort.words, fort.credit, fort.width, fort.height) == ("image", "Red Fort at dusk", "ex.com",
                                                                            1920, 1280)
    assert (gate.words, gate.credit, gate.width, gate.height) == ("us at the gate", "", 1200, 1600)
    assert fort.path == folder / "assets" / "img1.jpg" and fort.path.is_file()
    assert (waves.kind, waves.credit, waves.width, waves.height) == ("clip", "Pexels, by B", 1280, 720)
    assert 1.9 <= waves.seconds <= 2.05 and waves.path == folder / "assets" / "clip1.webm"
    assert sorted(p.name for p in (folder / "assets").iterdir()) == ["clip1.webm", "img1.jpg", "img3.jpg"]


async def test_a_clip_without_a_credit_is_credited_to_its_site(tmp_path, sources):
    _pictures, clip_bytes = sources
    waves = await make_clip(tmp_path / "waves.mp4", 1, size="320x240")
    clip_bytes["https://www.ex.com/waves.mp4"] = waves.read_bytes()
    _, clips = assets.parse(None, ["https://www.ex.com/waves.mp4 — waves, slow"])
    got, dropped = await assets.gather([], clips, tmp_path / "job")
    assert dropped == [] and got[0].credit == "ex.com"  # the credits card names every web clip, as it does a picture


async def test_in_a_private_chat_web_clips_are_dropped_with_the_decks_words(tmp_path, sources):
    pictures, clip_bytes = sources
    clip_bytes["https://ex.com/waves.mp4"] = b"never fetched"
    _, clips = assets.parse(None, ["https://ex.com/waves.mp4 — waves"])
    token = chat_turn.PRIVATE.set({"amazon.in"})
    try:
        got, dropped = await assets.gather([], clips, tmp_path / "job")
    finally:
        chat_turn.PRIVATE.reset(token)
    assert got == []
    assert dropped == ["clip1 couldn't be fetched: not fetched: this chat read a signed-in page, so photos from the "
                       "web aren't fetched here"]


async def test_a_clip_that_isnt_a_video_is_dropped_as_not_prepared(tmp_path, sources):
    _pictures, clip_bytes = sources
    clip_bytes["https://ex.com/page.mp4"] = b"<html>a page, not a clip</html>"
    _, clips = assets.parse(None, ["https://ex.com/page.mp4 — waves"])
    got, dropped = await assets.gather([], clips, tmp_path / "job")
    assert got == [] and dropped == ["clip1 couldn't be prepared: it isn't a video Odie can read"]  # no paths
    assert not any((tmp_path / "job" / "assets").iterdir())  # the download isn't left behind


async def test_what_would_go_over_the_stapled_cap_is_left_out(tmp_path, sources, monkeypatch):
    pictures, _clip_bytes = sources
    noisy = Image.effect_noise((1500, 1500), 120).convert("RGB")  # noise: a JPEG that stays big
    noisy.save(tmp_path / "noise.jpg", "JPEG", quality=95)
    pictures["https://ex.com/a.jpg"] = (tmp_path / "noise.jpg", "ex.com")
    pictures["https://ex.com/b.jpg"] = (tmp_path / "noise.jpg", "ex.com")
    images, _ = assets.parse(["https://ex.com/a.jpg — one", "https://ex.com/b.jpg — two"], None)
    first = (await assets.gather(images[:1], [], tmp_path / "probe"))[0][0]
    monkeypatch.setattr(assets, "MAX_STAPLED_BYTES", assets.stapled_size(first) + 1000)
    got, dropped = await assets.gather(images, [], tmp_path / "job")
    assert [a.name for a in got] == ["img1"]
    assert dropped == ["img2 was left out: the pictures and clips before it already fill what a video can carry"]
    assert not (tmp_path / "job" / "assets" / "img2.jpg").exists()


# What the writer reads, and what the page carries.

def an_asset(name, kind="image", words="Red Fort at dusk", credit="", width=1920, height=1280, seconds=0.0, path=None):
    return assets.Asset(name, kind, words, credit, width, height, seconds, path)


def test_the_listing_names_sizes_and_words_each_asset():
    listing = assets.listing(
        [an_asset("img1"), an_asset("img2", words="Nathula pass, us at the gate, 12 May 2026", width=1200, height=1600),
         an_asset("img10", words="a square map", width=800, height=800),
         an_asset("clip1", "clip", "waves on a Goa beach, slow", "Pexels, by B", 1280, 720, 12.04)],
        ["img4 couldn't be fetched: The link answered 404."])
    assert listing == (
        "Pictures (use by name with s.photo / s.texture; you cannot add others):\n"
        "  img1   1920×1280  landscape  Red Fort at dusk\n"
        "  img2   1200×1600  portrait   Nathula pass, us at the gate, 12 May 2026\n"
        "  img10  800×800    square     a square map\n"
        "Clips (use by name with s.clip; you cannot add others):\n"
        "  clip1  1280×720  landscape  12 s  waves on a Goa beach, slow\n"
        "Left out (don't use these names):\n"
        "  img4 couldn't be fetched: The link answered 404.")


def test_the_listing_is_empty_without_assets_and_tells_drops_alone():
    assert assets.listing([], []) == ""
    assert assets.listing([], ["img1 couldn't be fetched: x"]) == ("Left out (don't use these names):\n"
                                                                  "  img1 couldn't be fetched: x")


def test_the_staple_carries_each_asset_as_a_data_uri(tmp_path):
    picture = jpeg_file(tmp_path / "img1.jpg", 40, 30)
    clip = tmp_path / "clip1.webm"
    clip.write_bytes(b"\x1a\x45\xdf\xa3 pretend webm")
    script = assets.staple([an_asset("img1", width=40, height=30, path=picture),
                            an_asset("clip1", "clip", "waves", "", 1280, 720, 12.5, clip)])
    assert script.startswith("<script>Video.assets(") and script.endswith(")</script>")
    registry = json.loads(script[len("<script>Video.assets("):-len(")</script>")])
    assert list(registry) == ["img1", "clip1"]
    img1, clip1 = registry["img1"], registry["clip1"]
    assert (img1["kind"], img1["width"], img1["height"]) == ("image", 40, 30) and "seconds" not in img1
    assert img1["src"] == "data:image/jpeg;base64," + base64.b64encode(picture.read_bytes()).decode()
    assert (clip1["kind"], clip1["width"], clip1["height"], clip1["seconds"]) == ("clip", 1280, 720, 12.5)
    assert clip1["src"].startswith("data:video/webm;base64,")
    assert "Red Fort" not in script and "waves" not in script  # the words are the writer's, not the page's
    assert assets.staple([]) == ""


def test_the_staple_refuses_more_than_60_mb(tmp_path, monkeypatch):
    assert assets.MAX_STAPLED_BYTES == 60 * 1024 * 1024
    big = tmp_path / "img1.jpg"
    big.write_bytes(b"\xff" * 3000)
    asset = an_asset("img1", path=big)
    assert assets.stapled_size(asset) == len("data:image/jpeg;base64,") + 4000
    monkeypatch.setattr(assets, "MAX_STAPLED_BYTES", 4000)
    with pytest.raises(assets.AssetProblem, match="over the 60 MB"):
        assets.staple([asset])


def test_credits_are_the_web_ones_in_order_once_each():
    got = [an_asset("img1", credit="Photo by A on Unsplash"), an_asset("img2"),
           an_asset("img3", credit="Photo by A on Unsplash"), an_asset("clip1", "clip", credit="Pexels, by B")]
    assert assets.credits(got) == ["Photo by A on Unsplash", "Pexels, by B"]


def test_records_keep_no_data_and_bring_the_assets_back(tmp_path):
    asset = an_asset("clip1", "clip", "waves", "Pexels, by B", 1280, 720, 12.5, tmp_path / "assets" / "clip1.webm")
    record = assets.as_record(asset)
    assert record == {"name": "clip1", "kind": "clip", "words": "waves", "credit": "Pexels, by B", "width": 1280,
                      "height": 720, "seconds": 12.5, "file": "clip1.webm"}
    assert json.loads(json.dumps(record)) == record
    assert assets.from_records([record], tmp_path / "assets") == [asset]


def test_the_brief_keeps_the_lines_as_the_chat_gave_them():
    section = assets.brief_section(["https://ex.com/a.jpg — Akbar (Photo by A on Unsplash)", "photo:3F2A — us"],
                                   ["https://ex.com/v.mp4 — waves"])
    assert section == ("## Pictures\n\n"
                       "- https://ex.com/a.jpg — Akbar (Photo by A on Unsplash)\n"
                       "- photo:3F2A — us\n\n"
                       "Clips:\n\n"
                       "- https://ex.com/v.mp4 — waves")
    assert assets.brief_section([], []) == ""
    assert assets.brief_section([], ["https://ex.com/v.mp4 — waves"]) == ("## Pictures\n\n"
                                                                        "Clips:\n\n"
                                                                        "- https://ex.com/v.mp4 — waves")



# A failed fetch never fails the video: the asset is dropped and the writer told; the same address twice is one fetch.

def jpeg_bytes(w=800, h=600):
    out = io.BytesIO()
    Image.new("RGB", (w, h), RED).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def internet(isolated_settings, monkeypatch):
    """The real photos.fetch and safe_download over a MockTransport: "down.example" refuses to connect, anything else
    answers with a JPEG. Every request is counted by its address."""
    import httpx

    from odie import net
    requests = []

    async def resolve(host):
        return ["93.184.216.34"]

    def handler(request):
        requests.append(str(request.url))
        if request.url.host == "down.example":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=jpeg_bytes())

    monkeypatch.setattr(net, "resolve_host", resolve)
    monkeypatch.setattr(net, "_transport", httpx.MockTransport(handler))
    return requests


async def test_a_picture_or_clip_that_cant_connect_is_dropped_and_the_rest_kept(tmp_path, internet):
    images, clips = assets.parse(["https://down.example/a.jpg — Akbar", "https://ex.com/b.jpg — Babur"],
                                 ["https://down.example/v.mp4 — waves"])
    got, dropped = await assets.gather(images, clips, tmp_path / "job")
    assert [a.name for a in got] == ["img2"]
    assert dropped == ["img1 couldn't be fetched: The link couldn't be reached.",
                       "clip1 couldn't be fetched: The link couldn't be reached."]


async def test_anything_unexpected_with_one_picture_drops_it_and_keeps_the_rest(tmp_path, sources, monkeypatch, caplog):
    pictures, _clip_bytes = sources
    pictures["https://ex.com/a.jpg"] = (jpeg_file(tmp_path / "a.jpg", 400, 300), "ex.com")
    pictures["https://ex.com/b.jpg"] = (jpeg_file(tmp_path / "b.jpg", 400, 300), "ex.com")
    real_prepare = assets.prepare_image

    def breaks_on_the_first(src, dest):
        if dest.name == "img1.jpg":
            raise ValueError("/Users/asha/private/path broke")
        return real_prepare(src, dest)

    monkeypatch.setattr(assets, "prepare_image", breaks_on_the_first)
    images, _ = assets.parse(["https://ex.com/a.jpg — one", "https://ex.com/b.jpg — two"], None)
    got, dropped = await assets.gather(images, [], tmp_path / "job")
    assert [a.name for a in got] == ["img2"]
    assert dropped == ["img1 couldn't be used: something went wrong (see Odie's log)"]  # no path for the writer
    assert "img1" in caplog.text and "ValueError" in caplog.text  # the details are in the log


async def test_the_same_address_twice_is_fetched_once_and_gives_two_pictures(tmp_path, internet):
    images, _ = assets.parse(["https://ex.com/fort.jpg — the fort at dusk (Photo by A on Unsplash)",
                              "https://ex.com/fort.jpg — the fort again, closer"], None)
    got, dropped = await assets.gather(images, [], tmp_path / "job")
    assert dropped == [] and internet == ["https://ex.com/fort.jpg"]
    first, second = got
    assert (first.name, first.words, first.credit) == ("img1", "the fort at dusk", "Photo by A on Unsplash")
    assert (second.name, second.words, second.credit) == ("img2", "the fort again, closer", "ex.com")
    assert first.path.is_file() and second.path.is_file() and first.path != second.path
