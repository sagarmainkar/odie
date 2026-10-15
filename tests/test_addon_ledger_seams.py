"""The seams the ledger uses: closing a thread at its source, prefetched blocks, and stripping them from old turns."""

import httpx
import pytest
from google.genai import types

from odie import addons
from odie.addons import Addon
from odie.store.db import Store

OPEN, CLOSE = "[from your doorbell: possibly relevant]", "[/from your doorbell]"


@pytest.fixture(autouse=True)
def no_addons_after():
    yield
    addons.use(None)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def _bell(seen, fail=False):
    async def done(kind, ref):
        if kind != "doorbell":
            return None
        seen.append((kind, ref))
        if fail:
            raise RuntimeError("bell offline")
        return f"Doorbell: chime {ref} silenced"
    return Addon("bell", task_done=done)


async def test_task_done_reaches_the_addon(store):
    from odie.agent.tools.local import make_local_tools
    from odie.agent.agent import source_done
    seen = []
    addons.use([_bell(seen)])
    t = {x.name: x for x in make_local_tools(store, "Asia/Kolkata", source_done=source_done)}
    tid, _ = store.upsert_source_task("doorbell", "7", "Bell rang twice", "todo")
    out = await t["task_update"].func(task_id=tid, status="done")
    assert out.endswith(". Doorbell: chime 7 silenced") and seen == [("doorbell", "7")]
    tid2, _ = store.upsert_source_task("doorbell", "8", "Bell rang again", "todo")
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            r = (await c.post(f"/api/tasks/{tid2}/done")).json()
    assert r == {"ok": True, "ledger": "Doorbell: chime 8 silenced"} and seen[-1] == ("doorbell", "8")


async def test_task_done_survives_a_failing_addon(store):
    from odie.agent.agent import source_done
    from odie.agent.tools.local import make_local_tools
    addons.use([_bell([], fail=True)])
    t = {x.name: x for x in make_local_tools(store, "Asia/Kolkata", source_done=source_done)}
    tid, _ = store.upsert_source_task("doorbell", "7", "Bell rang twice", "todo")
    out = await t["task_update"].func(task_id=tid, status="done")
    assert out.endswith("status=done") and store.one("select status from tasks where id=?", (tid,))["status"] == "done"


async def test_a_thread_of_no_addons_kind_just_closes(store):
    from odie.agent.agent import source_done
    from odie.agent.tools.local import make_local_tools
    seen = []
    addons.use([_bell(seen)])
    t = {x.name: x for x in make_local_tools(store, "Asia/Kolkata", source_done=source_done)}
    tid = store.add_task("Call the plumber", "todo", source_kind="ref", source_ref="m1")
    out = await t["task_update"].func(task_id=tid, status="done")
    assert out.endswith("status=done") and seen == []


async def test_addon_prefetch_blocks_join_the_message():
    from odie.agent import prefetch

    async def bell(current, previous):
        return f"{OPEN}\n- rang at 09:10\n{CLOSE}"

    async def gate(current, previous):
        return "[from your gate]\n- opened\n[/from your gate]"

    async def broken(current, previous):
        raise RuntimeError("down")
    addons.use([Addon("bell", prefetch=bell), Addon("broken", prefetch=broken), Addon("gate", prefetch=gate)])
    out = await prefetch.gather("Who rang the doorbell this morning?", [])
    assert out.index(OPEN) < out.index("[from your gate]") and "down" not in out


def test_old_turns_lose_addon_blocks():
    from odie.agent.compaction import compact
    from odie.agent.prefetch import strip_blocks
    from odie.app.runner import strip_trailer
    addons.use([Addon("bell", blocks=((OPEN, CLOSE),))])
    text = f"Who rang?\n\n{OPEN}\n- rang at 09:10\n{CLOSE}\n\n[context: now 09:30 Tue 6 Oct]"
    assert strip_blocks(text) == "Who rang?\n\n[context: now 09:30 Tue 6 Oct]"
    assert strip_trailer(text) == "Who rang?"
    turns = [types.Content(role="user", parts=[types.Part(text=text)]) for _ in range(3)]
    assert compact(turns) == turns  # a short chat: sent as it was
    squeezed = compact(turns, limit=100, keep=0)  # a cut at the last message: the two before go as words only
    assert OPEN not in squeezed[0].parts[0].text and OPEN in squeezed[-1].parts[-1].text


async def test_a_prefetch_hook_that_isnt_async_or_raises_at_once_is_contained():
    from odie.agent import prefetch

    def plain(current, previous):  # not async: awaiting its result fails
        return "[from your gate]\n- opened\n[/from your gate]"

    def raises(current, previous):
        raise RuntimeError("down")

    async def bell(current, previous):
        return f"{OPEN}\n- rang at 09:10\n{CLOSE}"
    addons.use([Addon("plain", prefetch=plain), Addon("raises", prefetch=raises), Addon("bell", prefetch=bell)])
    out = await prefetch.gather("Who rang the doorbell this morning?", [])
    assert OPEN in out and "[from your gate]" not in out
