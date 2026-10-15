import io

from PIL import Image

from odie import persona
from odie.store.db import Store


def _store(tmp_path):
    s = Store(tmp_path / "a.db"); s.init_schema(); return s


def test_default_and_rename(tmp_path):
    s = _store(tmp_path)
    assert persona.get(s) == {"name": "Odie", "avatar": None}
    assert persona.set_name(s, "  Mira  ")["name"] == "Mira"
    assert persona.get(s)["name"] == "Mira"
    assert persona.set_name(s, "")["name"] == "Odie"          # empty resets
    assert persona.set_name(s, "x" * 60)["name"] == "x" * 24  # capped


def test_apply_name_replaces_whole_words_only():
    assert persona.apply_name("You are Odie, Asha's assistant. Melodie stays.", "Mira") == "You are Mira, Asha's assistant. Melodie stays."
    assert persona.apply_name("You are Odie.", "Odie") == "You are Odie."


def test_avatar_is_square_and_small(tmp_path):
    s = _store(tmp_path)
    buf = io.BytesIO(); Image.new("RGB", (1200, 800), (200, 120, 60)).save(buf, "PNG")
    p = persona.save_avatar(s, buf.getvalue(), tmp_path / "av")
    path = persona.avatar_path(p["avatar"], tmp_path / "av")
    img = Image.open(path)
    assert img.size == (persona.AVATAR_PX, persona.AVATAR_PX) and img.format == "JPEG"
    assert persona.clear_avatar(s)["avatar"] is None
    assert persona.avatar_path("../etc/passwd", tmp_path / "av") is None

