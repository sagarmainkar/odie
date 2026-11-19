"""/api/health says which web build the server serves (web/dist/build.txt), so an open app can tell it is behind."""
import dataclasses

import pytest
from starlette.testclient import TestClient

from odie import config, update
from odie.app.main import create_app
from odie.store.db import Store
from tests.test_api import FakeRunner


def test_the_build_is_read_from_the_served_folder(tmp_path):
    (tmp_path / "build.txt").write_text("a1b2c3d\n")
    assert update.web_build(tmp_path) == "a1b2c3d"


def test_no_build_file_or_an_odd_one_says_nothing(tmp_path):
    assert update.web_build(tmp_path) == ""  # an older build has no file
    (tmp_path / "build.txt").write_text("<script>\n")
    assert update.web_build(tmp_path) == ""  # only a short commit-like word is passed on


@pytest.fixture
def client(isolated_settings, tmp_path, monkeypatch):
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))  # never the real install
    monkeypatch.setenv("ODIE_PAIRING", "off")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "build.txt").write_text("e4f5a6b\n")
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, web_dist=dist))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    with TestClient(create_app(runner=FakeRunner(), store=store)) as c:
        yield c


def test_health_says_the_build(client):
    assert client.get("/api/health").json()["build"] == "e4f5a6b"
