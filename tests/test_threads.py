import time

import pytest
from google.adk.events import Event
from google.genai import types

from odie import config, threads
from odie.app.runner import CHECK_PREFIX, NEW_CHAT, OdieRunner
from odie.store.db import Store
from tests.test_api import client  # noqa: F401  (fixture)


async def _say(r: OdieRunner, sid: str, author: str, text: str, ts: float):
    s = config.settings
    await r._ensure_session(sid)
    sess = await r.session_service.get_session(app_name=s.app_name, user_id=s.user_id, session_id=sid)
    ev = Event(author=author, invocation_id="i", timestamp=ts,
               content=types.Content(role="user" if author == "user" else "model", parts=[types.Part(text=text)]))
    await r.session_service.append_event(session=sess, event=ev)


@pytest.fixture
async def runner(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    t = time.time() - 86400 * 3
    await _say(r, "chat-2026-10-02", "user", "Plan a trip to Goa for the long weekend\n\n[context: Friday]", t)
    await _say(r, "chat-2026-10-02", "odie", "Here's a 3-day Goa plan: beaches in the north.", t + 5)
    await _say(r, "chat-2026-10-04", "user", CHECK_PREFIX + "call task_add", t + 86400)
    await _say(r, "chat-2026-10-04", "user", "How is TCS doing?", t + 86401)
    await _say(r, "chat-2026-10-05", "odie", NEW_CHAT, t + 2 * 86400)                       # an empty fresh start
    await _say(r, "voice-2026-10-05", "user", "Talk mode question", t + 2 * 86400)          # not a chat thread
    yield r
    await r.close()


async def test_lists_chat_threads_newest_first_with_titles(runner):
    rows = threads.list_threads(runner.store)
    assert [(t["id"], t["title"]) for t in rows] == [("chat-2026-10-04", "How is TCS doing?"),
                                                    ("chat-2026-10-02", "Plan a trip to Goa for the long weekend")]
    assert rows[1]["date"] == "2026-10-02" and rows[1]["messages"] == 2 and rows[0]["pinned"] is False


async def test_pin_rename_and_order(runner):
    threads.set_pinned(runner.store, "chat-2026-10-02", True)
    threads.rename(runner.store, "chat-2026-10-02", "Goa weekend")
    rows = threads.list_threads(runner.store)
    assert rows[0]["id"] == "chat-2026-10-02" and rows[0]["pinned"] and rows[0]["title"] == "Goa weekend"
    threads.rename(runner.store, "chat-2026-10-02", "")          # back to the first message
    assert threads.list_threads(runner.store)[0]["title"].startswith("Plan a trip")
    threads.set_pinned(runner.store, "chat-2026-10-02", False)
    assert threads.list_threads(runner.store)[0]["id"] == "chat-2026-10-04"


async def test_search_finds_words_in_any_message(runner):
    rows = threads.list_threads(runner.store, q="beaches")
    assert [t["id"] for t in rows] == ["chat-2026-10-02"] and "beaches" in rows[0]["snippet"]
    assert threads.list_threads(runner.store, q="nothing like this") == []


async def test_one_threads_history(runner):
    h = await runner.session_history("chat-2026-10-02", limit=30)
    assert [i["role"] for i in h["items"]] == ["user", "odie"] and h["items"][0]["text"].startswith("Plan a trip")


def test_thread_ids_are_checked():
    assert threads.valid_id("chat-2026-10-02") and threads.valid_id("chat-2026-10-02-3")
    assert not threads.valid_id("voice-2026-10-02") and not threads.valid_id("../etc") and not threads.valid_id("chat-x")


async def test_thread_routes(client):
    r = await client.get("/api/threads")
    assert r.status_code == 200 and "threads" in r.json()
    assert (await client.post("/api/threads/voice-1/pin", json={"pinned": True})).status_code == 404
    assert (await client.post("/api/threads/chat-2026-10-02/pin", json={"pinned": True})).json()["pinned"] is True
    assert (await client.post("/api/threads/chat-2026-10-02/rename", json={"title": "Goa"})).json()["title"] == "Goa"


async def test_the_desk_is_listed_first_and_pinned_with_only_odies_posts(runner):
    # The watch posts its news to the Desk; nobody has written there yet, but it must show at the top of Chats.
    await runner.post_message("Good morning: two things need you.", session_id=threads.DESK)
    rows = threads.list_threads(runner.store)
    assert rows[0]["id"] == "chat-desk" and rows[0]["title"] == "Desk" and rows[0]["pinned"] is True
    assert len(rows[0]["date"]) == 10 and rows[0]["date"][4] == "-"  # a real date, like the other rows
    assert [t["id"] for t in rows[1:]] == ["chat-2026-10-04", "chat-2026-10-02"]


async def test_the_desk_can_be_renamed_and_unpinned(runner):
    """The Desk starts pinned and named "Desk", but it is the user's list: a new name sticks, and so does an unpin."""
    from odie import threads
    await runner.post_message("Good morning: two things need you.", session_id=threads.DESK)
    threads.rename(runner.store, threads.DESK, "Inbox duty")
    threads.set_pinned(runner.store, threads.DESK, False)
    desk = next(t for t in threads.list_threads(runner.store) if t["id"] == threads.DESK)
    assert desk["title"] == "Inbox duty" and desk["renamed"] is True
    assert desk["pinned"] is False
    threads.set_pinned(runner.store, threads.DESK, True)
    desk = next(t for t in threads.list_threads(runner.store) if t["id"] == threads.DESK)
    assert desk["pinned"] is True


async def test_no_desk_until_something_is_posted_there(runner):
    assert all(t["id"] != threads.DESK for t in threads.list_threads(runner.store))


def test_the_desk_id_is_a_valid_thread():
    assert threads.valid_id("chat-desk") and not threads.valid_id("chat-deskx") and not threads.valid_id("chat-desk-2")
