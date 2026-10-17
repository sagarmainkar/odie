"""A deck end to end (what make_deck's job builds): Markdown in; one card's media out (the PDF with its deck: the
PowerPoint, the previews); files in the workspace (never overwriting an older deck's); failed photos reported; without
Chrome the PowerPoint still arrives; limits say what to cut."""
import io

import pytest
from PIL import Image

from odie import media
from odie.decks import build, photos
from tests.test_decks_model import MEGHALAYA


class FakeBrowser:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def render(self, html, width, height, pages, timeout=60):
        from odie.browser.engine import BrowserError
        self.calls.append((width, height, pages, len(html)))
        if self.fail:
            raise BrowserError("The deck couldn't be rendered (TimeoutError).")
        out = io.BytesIO()
        Image.new("RGB", (width, height), (20, 40, 60)).save(out, "JPEG")
        return b"%PDF-1.7 fake", [out.getvalue()] * pages


@pytest.fixture
def no_web(monkeypatch, isolated_settings, tmp_path):
    async def fetch_all(refs):
        ok = {}
        for ref, credit in refs:
            if "gone" in ref:
                continue
            p = tmp_path / "p.jpg"
            Image.new("RGB", (800, 450), (1, 2, 3)).save(p, "JPEG")
            ok[ref] = photos.Photo(ref, p, 800, 450, credit or "ex.com")
        return ok, [r for r, _ in refs if "gone" in r]
    monkeypatch.setattr(build, "fetch_all", fetch_all)
    from odie.agent.tools.files import workspace_root
    assert str(tmp_path) in str(workspace_root())
    return tmp_path


async def test_a_deck_is_one_card_with_its_pdf_pptx_and_previews(no_web):
    from odie.agent.tools.files import workspace_root
    b = FakeBrowser()
    got = await build.make_deck(MEGHALAYA, "Meghalaya Trip Guide", "editorial", browser=b)
    m = got["media"]
    assert m["filename"] == "Meghalaya Trip Guide.pdf" and m["deck"]["slides"] == 9 and m["deck"]["theme"] == "editorial"
    assert m["deck"]["pptx"]["filename"] == "Meghalaya Trip Guide.pptx" and len(m["deck"]["pages"]) == 9
    thumb = media.get(m["deck"]["pages"][0]["thumb"])
    assert thumb[1]["kind"] == "page" and Image.open(thumb[0]).size == (480, 270)
    assert Image.open(media.get(m["deck"]["pages"][0]["view"])[0]).size == (1600, 900)
    assert media.get(m["id"])[1]["deck"]["slides"] == 9  # history reads the sidecar
    assert b.calls[0][:3] == (1920, 1080, 9)
    for ext in ("pdf", "pptx", "html", "deck.md"):
        assert (workspace_root() / f"Meghalaya Trip Guide.{ext}").is_file()
    assert "9 slides" in got["result"] and "PDF and a PowerPoint" in got["result"]


async def test_an_older_deck_with_the_same_name_is_kept(no_web):
    from odie.agent.tools.files import workspace_root
    (workspace_root() / "Plain.pptx").write_bytes(b"older deck")
    got = await build.make_deck("# A\n\n# B\n- x\n", "Plain", "", browser=None)
    assert got["media"]["filename"] == "Plain (2).pptx" and (workspace_root() / "Plain.pptx").read_bytes() == b"older deck"


async def test_a_failed_photo_falls_back_and_is_reported(no_web):
    got = await build.make_deck("# Cover\nimage: https://ex.com/gone.jpg\n\n# Two\n- a\n", "", "", browser=FakeBrowser())
    assert "https://ex.com/gone.jpg" in got["result"] and "media" in got


async def test_without_chrome_the_pptx_still_arrives(no_web):
    got = await build.make_deck("# A\n\n# B\n- x\n", "Plain", "", browser=None)
    assert got["media"]["filename"] == "Plain.pptx" and got["media"]["deck"]["pages"] == []
    assert "need Chrome" in got["media"]["deck"]["note"] and "error" not in got
    failed = await build.make_deck("# A\n\n# B\n- x\n", "Plain2", "", browser=FakeBrowser(fail=True))
    assert failed["media"]["filename"] == "Plain2.pptx" and "weren't available" in failed["media"]["deck"]["note"]


async def test_limits_come_back_as_an_error(no_web):
    got = await build.make_deck("# A\n\n# B\n" + "".join(f"- {i}\n" for i in range(9)), "", "", browser=FakeBrowser())
    assert got == {"error": "Slide 2 has 9 bullets; keep 6 or split it."}


async def test_a_builder_that_breaks_comes_back_as_an_error(no_web, monkeypatch):
    def broken(*a, **k):
        raise ValueError("max() iterable argument is empty")
    monkeypatch.setattr(build, "build_pptx", broken)
    got = await build.make_deck("# A\n\n# B\n- x\n", "Plain", "", browser=None)
    assert "error" in got and "couldn't be built" in got["error"]  # the turn goes on; the model hears why


async def test_building_never_blocks_the_chat(no_web, monkeypatch):
    import asyncio
    import time
    real = build.build_pptx

    def slow(*a, **k):
        time.sleep(0.6)  # a big deck: python-pptx over many photos
        return real(*a, **k)
    monkeypatch.setattr(build, "build_pptx", slow)
    gaps, last = [], time.monotonic()

    async def ticker():
        nonlocal last
        for _ in range(40):
            await asyncio.sleep(0.02)
            now = time.monotonic()
            gaps.append(now - last)
            last = now
    tick = asyncio.create_task(ticker())
    await build.make_deck("# A\n\n# B\n- x\n", "Plain", "", browser=FakeBrowser())
    await tick
    assert max(gaps) < 0.3  # the event loop kept running while the deck was built
