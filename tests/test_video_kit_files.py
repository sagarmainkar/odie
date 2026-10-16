"""The kit's vendored files are there, with their licences, and need nothing from the network."""
import re
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / "odie" / "video" / "kit"


def test_the_vendored_libraries_and_their_licences_ship():
    for name in ("three.min.js", "three.LICENSE", "katex.min.js", "katex.min.css", "katex.LICENSE"):
        assert (KIT / name).stat().st_size > 0, name
    assert list((KIT / "fonts").glob("*.woff2"))


def test_katex_css_points_only_at_its_own_fonts():
    css = (KIT / "katex.min.css").read_text()
    for url in re.findall(r"url\(([^)]+)\)", css):
        assert url.strip("'\"").startswith("fonts/"), url
