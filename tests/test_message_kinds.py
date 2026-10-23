"""Every message Odie says on its own tells the bus what it is, and the watch rings the bus when it pushes, so an
app without web push (the Mac) can show a banner for the right things and nothing for housekeeping."""
import asyncio

import pytest

from odie.app.events import EventBus
from odie.app.main import watch_pushed
from odie.app.runner import OdieRunner
from odie.store.db import Store


def _store(tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def _messages(q: asyncio.Queue) -> list[dict]:
    """Every event waiting on a subscriber's queue."""
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_a_message_says_its_kind_on_the_bus(isolated_settings, tmp_path):
    r = OdieRunner(_store(tmp_path))
    q = r.bus.queue()
    await r.post_message("Stopped.", session_id="chat-2026-10-01")
    await r.post_message("🔔 HDFC: crossed ₹1,800", session_id="chat-2026-10-01", kind="tracker")
    kinds = [(e["type"], e["kind"], e["text"]) for e in _messages(q)]
    assert kinds == [("message", "system", "Stopped."), ("message", "tracker", "🔔 HDFC: crossed ₹1,800")]
    await r.close()


async def test_a_tracker_that_fired_is_a_tracker(isolated_settings, tmp_path):
    r = OdieRunner(_store(tmp_path))
    q = r.bus.queue()
    await r.tracker_notify({"id": 7, "title": "HDFC"}, "crossed ₹1,800")
    [e] = _messages(q)
    assert e["kind"] == "tracker" and e["text"] == "🔔 HDFC: crossed ₹1,800"
    await r.close()


class Mac:
    """Stands in for the runner: only its bus matters here."""

    def __init__(self):
        self.bus = EventBus()


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    def fake_send(store, title, body, url="/", tag=None):
        sent.append((title, body, url, tag))
        return 1
    monkeypatch.setattr("odie.push.send.send_to_all", fake_send)
    return sent


async def test_a_watch_push_also_rings_the_bus(tmp_path, pushes):
    runner = Mac()
    q = runner.bus.queue()
    watch_pushed(_store(tmp_path), runner, "Deck from xyz", "made from the PDF")
    assert pushes == [("Deck from xyz", "made from the PDF", "/#today", "watch")]
    [e] = _messages(q)
    assert e["type"] == "watch" and e["title"] == "Deck from xyz" and e["body"] == "made from the PDF" and e["ts"] > 0


async def test_a_failed_push_still_rings_the_bus(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("no VAPID key")
    monkeypatch.setattr("odie.push.send.send_to_all", broken)
    runner = Mac()
    q = runner.bus.queue()
    watch_pushed(_store(tmp_path), runner, "Mail stopped working", "Fix it in Settings → Connected apps.")
    assert [e["type"] for e in _messages(q)] == ["watch"]
