"""The kit's vendored files are there, with their licences, and need nothing from the network."""
import re
from pathlib import Path

from odie.browser import RENDER_ARGS
from odie.browser.engine import Browser
from odie.video import page
from tests.test_video_kit import BIN, needs_browser

KIT = Path(__file__).resolve().parent.parent / "odie" / "video" / "kit"


def test_the_vendored_libraries_and_their_licences_ship():
    for name in ("three.min.js", "three.LICENSE", "katex.min.js", "katex.min.css", "katex.LICENSE"):
        assert (KIT / name).stat().st_size > 0, name
    assert list((KIT / "fonts").glob("*.woff2"))


def test_katex_css_points_only_at_its_own_fonts():
    css = (KIT / "katex.min.css").read_text()
    for url in re.findall(r"url\(([^)]+)\)", css):
        assert url.strip("'\"").startswith("fonts/"), url


def test_the_3d_character_libraries_ship_with_their_licences():
    for name in ("gltf-loader.js", "three-vrm.min.js", "three-vrm.LICENSE"):
        assert (KIT / name).stat().st_size > 0, name
    vrm_head = (KIT / "three-vrm.min.js").read_text()[:400]
    loader_head = (KIT / "gltf-loader.js").read_text()[:400]
    assert "pixiv" in vrm_head and "three-vrm 3.5.5" in vrm_head and "MIT" in vrm_head
    assert "three.js r158" in loader_head and "MIT" in loader_head
    readme = (KIT / "README.md").read_text()
    assert "three-vrm 3.5.5" in readme and "GLTFLoader" in readme and "0.158.0" in readme


def test_the_3d_character_libraries_are_plain_scripts():
    for name in ("gltf-loader.js", "three-vrm.min.js"):
        text = (KIT / name).read_text()
        assert not re.search(r'(^|[;}\s])import\s*[\w*{]', text), name
        assert 'from"three"' not in text and "from 'three'" not in text, name
        assert not re.search(r'(^|[;}\s])export\s*[{d]', text), name


@needs_browser
async def test_the_3d_character_libraries_load_in_a_sealed_tab(tmp_path):
    # three.min.js is already in every page; the two libraries come after it, as plain scripts.
    scripts = "".join(f"<script>{(KIT / name).read_text()}</script>" for name in ("gltf-loader.js", "three-vrm.min.js"))
    body = scripts + "<script>Video.scenes([{draw(t, s) {}}]);</script>"
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(body, {"starts": [0.0], "lengths": [3.0]}), 1920, 1080) as p:
            kinds = await p.eval('typeof THREE.GLTFLoader + "," + typeof THREE_VRM.VRMLoaderPlugin')
            errors = list(p.errors)
    finally:
        await b.close()
    assert kinds == "function,function"
    assert errors == []
