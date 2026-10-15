"""One model for everything: the brief, memory review, summaries and background checks all use the
chat model; a saved "jobs" model from an older install is ignored, and only the chat model can be chosen."""
import httpx
import pytest

from odie.models import resolve_selection
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting("model.chat", {"provider": "ollama", "model": "glm-5.3-flash:cloud"})
    return s


def test_a_saved_jobs_model_is_ignored(store):
    store.set_setting("model.jobs", {"provider": "lmstudio", "model": "google/gemma-4-12b-qat"})  # an older install's choice
    for slot in ("jobs", "chat"):
        sel = resolve_selection(store, slot)
        assert sel.model == "glm-5.3-flash:cloud" and sel.slot == "chat"


async def test_only_the_chat_model_can_be_chosen(isolated_settings, tmp_path):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "b.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            r = await c.put("/api/models/selection", json={"slot": "jobs", "provider": "ollama", "model": "x"})
            assert r.status_code == 422 and s.get_setting("model.jobs") is None
            got = (await c.get("/api/models")).json()
            assert set(got["selection"]) == {"chat"}
            assert (await c.delete("/api/models/selection/jobs")).status_code in (404, 405)
