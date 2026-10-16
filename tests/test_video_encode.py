"""ffmpeg through imageio-ffmpeg: segments from JPEG frames, the final mux with the voice, and probe. Real ffmpeg."""
import io
import wave

import pytest
from PIL import Image

from odie.video import encode


def jpeg(colour):
    buf = io.BytesIO()
    Image.new("RGB", (320, 180), colour).save(buf, "JPEG")
    return buf.getvalue()


def silence(seconds, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


async def make_segment(path, colour, frames=15, fps=10):
    async with encode.Segment(path, fps=fps) as seg:
        for _ in range(frames):
            await seg.add(jpeg(colour))
    return path


async def test_two_segments_and_a_voice_make_one_video(tmp_path):
    parts = []
    for i, colour in enumerate(("red", "blue")):
        parts.append(await make_segment(tmp_path / f"seg{i}.mp4", colour))
    (tmp_path / "voice.wav").write_bytes(silence(3.0))
    out = tmp_path / "out.mp4"
    await encode.mux(parts, tmp_path / "voice.wav", out)
    info = await encode.probe(out)
    assert info["video"] and info["audio"] and abs(info["seconds"] - 3.0) < 0.15


async def test_the_video_is_in_the_colours_players_expect(tmp_path):
    # JPEG frames are full-range with the old SD colour matrix; players expect limited range and BT.709 for HD
    parts = [await make_segment(tmp_path / "seg0.mp4", "red")]
    (tmp_path / "voice.wav").write_bytes(silence(1.5))
    out = tmp_path / "out.mp4"
    await encode.mux(parts, tmp_path / "voice.wav", out)
    for path in (parts[0], out):  # the segment, and the MP4 its picture is copied into
        pixels = (await encode.probe(path))["pixels"]
        assert pixels.startswith("yuv420p(tv, bt709"), pixels


async def test_a_bad_frame_says_what_ffmpeg_said(tmp_path):
    with pytest.raises(encode.EncodeError) as caught:
        async with encode.Segment(tmp_path / "bad.mp4", fps=10) as seg:
            await seg.add(b"not a jpeg")
    assert str(caught.value).strip()


async def test_an_error_in_the_body_ends_ffmpeg_and_is_the_one_raised(tmp_path):
    seg = encode.Segment(tmp_path / "half.mp4", fps=10)
    with pytest.raises(RuntimeError, match="page crashed"):
        async with seg:
            await seg.add(jpeg("red"))
            raise RuntimeError("page crashed")
    assert seg.process.returncode is not None


async def test_paths_with_a_quote_survive_the_concat_list(tmp_path):
    folder = tmp_path / "Asha's job"
    folder.mkdir()
    parts = [await make_segment(folder / "seg0.mp4", "red")]
    (folder / "voice.wav").write_bytes(silence(1.5))
    out = folder / "out.mp4"
    await encode.mux(parts, folder / "voice.wav", out)
    info = await encode.probe(out)
    assert info["video"] and info["audio"]


async def test_probe_reads_a_video_and_a_voice(tmp_path):
    video = await make_segment(tmp_path / "seg.mp4", "red")
    voice = tmp_path / "voice.wav"
    voice.write_bytes(silence(2.0))
    video_info = await encode.probe(video)
    voice_info = await encode.probe(voice)
    assert video_info["video"] and not video_info["audio"]
    assert abs(video_info["seconds"] - 1.5) < 0.15
    assert voice_info["audio"] and not voice_info["video"] and voice_info["pixels"] == ""
    assert abs(voice_info["seconds"] - 2.0) < 0.05


def test_concat_line_escapes_single_quotes(tmp_path):
    line = encode.concat_line(tmp_path / "Asha's seg.mp4")
    assert line == f"file '{tmp_path}/Asha'\\''s seg.mp4'"
