import httpx
import pytest

from odie.app.main import create_app
from odie.store.db import Store
from tests.test_approvals import FakeRunner


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        yield c


async def test_profile_starts_without_a_name_and_with_the_computers_region(client):
    from odie import config
    p = (await client.get("/api/profile")).json()
    assert p["user_name"] == ""
    assert (p["timezone"], p["locale"], p["country"], p["currency"]) == (config.settings.timezone, config.settings.locale,
                                                                         config.settings.country, config.settings.currency)
    assert p["machine"] in ("Mac", "computer")


async def test_saving_a_name_trims_and_caps_it(client):
    assert (await client.put("/api/profile", json={"user_name": "  Asha   Rao  "})).json()["user_name"] == "Asha Rao"
    assert len((await client.put("/api/profile", json={"user_name": "x" * 90})).json()["user_name"]) == 40
    assert (await client.put("/api/profile", json={"user_name": "   "})).json()["user_name"] == ""
    assert (await client.get("/api/profile")).json()["user_name"] == ""


def test_machine_kind():
    from odie.profile import machine_kind
    assert machine_kind("darwin") == "Mac" and machine_kind("linux") == "computer"
