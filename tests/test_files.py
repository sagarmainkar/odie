"""Attachments: make_file writes a text file (a spreadsheet, notes, a page, data, a calendar event) into Odie's
workspace and hands it to the chat; attach_file hands over a file made there by a skill or the shell. Nothing outside
the workspace, and every download is a download: never a page that runs on Odie's address."""
import os

import httpx
import pytest

from odie import media
from odie.agent.tools import files as ftools
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def tools():
    return {t.name: t for t in ftools.make_file_tools()}


async def test_make_file(store):
    out = await tools()["make_file"].func(name="Goa packing list.csv", content="item,qty\nsunscreen,1\n", title="Goa packing list")
    m = out["media"]
    assert m["kind"] == "file" and m["filename"] == "Goa packing list.csv" and m["size"] == 21 and "under your reply" in out["result"]
    assert (ftools.workspace() / "Goa packing list.csv").read_text() == "item,qty\nsunscreen,1\n"
    path, saved = media.get(m["id"])
    assert path.read_text() == "item,qty\nsunscreen,1\n" and saved["mime"] == "text/csv" and saved["title"] == "Goa packing list"


async def test_make_file_names_are_safe_and_never_overwrite(store):
    t = tools()["make_file"]
    assert (await t.func(name="../../etc/x.csv", content="a"))["media"]["filename"] == "x.csv"
    assert (await t.func(name="x.csv", content="b"))["media"]["filename"] == "x (2).csv"  # never overwrites
    assert (await t.func(name="bad\x00na\nme:?.md", content="c"))["media"]["filename"] == "badname.md"
    assert (ftools.workspace() / "x.csv").read_text() == "a"
    assert "extension" in (await t.func(name="notes", content="d"))["error"]
    assert "documents skill" in (await t.func(name="run.exe", content="e"))["error"]
    assert sorted(p.name for p in ftools.workspace().iterdir()) == ["badname.md", "x (2).csv", "x.csv"]


async def test_attach_a_file_from_the_workspace(store):
    (ftools.workspace() / "deck.pptx").write_bytes(b"PK\x03\x04 a deck")
    out = await tools()["attach_file"].func(path="deck.pptx")
    m = out["media"]
    assert m["filename"] == "deck.pptx" and m["title"] == "deck.pptx"
    assert media.get(m["id"])[1]["mime"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    again = await tools()["attach_file"].func(path=str(ftools.workspace() / "deck.pptx"), title="The deck")
    assert again["media"]["title"] == "The deck"


async def test_attach_refuses_files_outside_the_workspace(store, isolated_settings, tmp_path):
    t = tools()["attach_file"]
    ws = ftools.workspace()
    (tmp_path / "secret.txt").write_text("no")
    os.symlink(tmp_path / "secret.txt", ws / "link.txt")
    (ws / "folder").mkdir()
    for bad in ("../assistant.db", str(tmp_path / "secret.txt"), "link.txt", "/etc/hosts", "folder", "missing.csv"):
        out = await t.func(path=bad)
        assert "error" in out and "media" not in out, bad
    assert str(ws) in (await t.func(path="/etc/hosts"))["error"]  # says where files can be attached from


async def test_files_are_downloads_not_pages(store, tmp_path):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    out = await tools()["make_file"].func(name="page.html", content="<script>alert(document.cookie)</script>")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        r = await c.get(f"/api/media/{out['media']['id']}")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment") and "page.html" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["content-security-policy"] == "sandbox"


async def test_size_limits(store):
    assert "1 MB" in (await tools()["make_file"].func(name="big.txt", content="x" * 1_000_001))["error"]
    big = ftools.workspace() / "huge.bin"
    with open(big, "wb") as f:
        f.truncate(50 * 1024 * 1024 + 1)
    assert "50 MB" in (await tools()["attach_file"].func(path="huge.bin"))["error"]


def test_the_tools_say_when_to_use_them():
    t = tools()
    assert ".csv" in t["make_file"].description and ".ics" in t["make_file"].description and "documents skill" in t["make_file"].description
    assert "workspace" in t["attach_file"].description


async def test_odd_extensions_and_disk_errors_are_plain(store, monkeypatch):
    t = tools()
    for name in ("settings.properties", "app.webmanifest", "a.c++"):
        (ftools.workspace() / name).write_text("x=1")
        out = await t["attach_file"].func(path=name)
        assert out["media"]["filename"] == name, out  # stored under a plain extension, downloaded under its own name
    out = await t["attach_file"].func(path="report.pdf")
    assert str(ftools.workspace()) in out["error"]  # says where to put it

    def full(self, data):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(type(ftools.workspace()), "write_bytes", full)
    assert "error" in await t["make_file"].func(name="list.csv", content="a")


# ── shown, not downloaded (2026-10-14): a picture, a video or an audio file plays under the reply ──
async def test_a_picture_a_video_and_a_sound_are_their_own_kinds(store):
    from odie.agent.tools.files import hand_over, workspace
    ws = workspace()
    (ws / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
    (ws / "clip.MP4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40)
    (ws / "tune.m4a").write_bytes(b"\x00" * 20)
    (ws / "data.bin").write_bytes(b"\x00" * 20)
    out = hand_over(ws / "logo.svg")
    assert out["media"]["kind"] == "picture" and "under your reply" in out["result"] and "download" not in out["result"]
    assert hand_over(ws / "clip.MP4")["media"]["kind"] == "video"
    assert hand_over(ws / "tune.m4a")["media"]["kind"] == "audio"
    assert hand_over(ws / "data.bin")["media"]["kind"] == "file"


async def test_make_file_can_write_an_svg(store):
    from odie.agent.tools.files import make_file_tools
    make = {t.name: t for t in make_file_tools()}["make_file"].func
    out = await make(name="plan.svg", content='<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>')
    assert out["media"]["kind"] == "picture" and out["media"]["filename"] == "plan.svg"


async def test_pictures_and_videos_are_served_to_show_not_to_download(store, tmp_path):
    from odie.agent.tools.files import hand_over, workspace
    ws = workspace()
    (ws / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>')
    (ws / "clip.mp4").write_bytes(bytes(range(200)))
    pic = hand_over(ws / "logo.svg")["media"]
    vid = hand_over(ws / "clip.mp4")["media"]
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        r = await c.get(f"/api/media/{pic['id']}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        assert "attachment" not in r.headers.get("content-disposition", "")  # shown inline
        assert r.headers["content-security-policy"] == "sandbox" and r.headers["x-content-type-options"] == "nosniff"  # an SVG never runs
        r = await c.get(f"/api/media/{vid['id']}", headers={"Range": "bytes=10-19"})
        assert r.status_code == 206 and r.content == bytes(range(10, 20)) and r.headers["accept-ranges"] == "bytes"  # the phone scrubs
        assert "attachment" not in r.headers.get("content-disposition", "")
