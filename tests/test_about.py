from types import SimpleNamespace

import pytest

from odie import about, trackers
from odie.store.db import Store


@pytest.fixture
def runner(isolated_settings, tmp_path, monkeypatch):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    monkeypatch.setattr("odie.voice.load_secret", lambda name: None)
    skill = SimpleNamespace(name="travel-itinerary", source="user", status="ok", description="Plans trips day by day.")
    app = SimpleNamespace(name="vault", status="ok", enabled=True, description="Obsidian notes", tools=["search_notes", "read_note"])
    r = SimpleNamespace(store=s, plugins={"skills": [skill], "servers": [app]},
                        _all_tool_names=lambda: {"gmail_search": "Odie", "web_search": "Odie", "life_admin": "Odie", "run_shell": "Odie"})
    about.hooks["runner"] = r
    yield r
    about.hooks["runner"] = None


def test_features_reports_what_is_really_there(runner):
    trackers.create(runner.store, "Arsenal v Spurs", "score", "15m")
    t = about.features()
    assert "Mail (Gmail)" not in t and "Money and messages" not in t and "Web:" in t and "Commands on this computer" in t
    assert "Calendar" not in t and "Tasks and reminders" not in t          # their tools aren't present here
    assert "travel-itinerary (the user's own): Plans trips" in t
    assert "vault (ok): Obsidian notes; tools: search_notes, read_note" in t
    assert "Model:" in t and "background work" in t and "Jobs" not in t and "LM Studio" in t and "Read-aloud: Kokoro" in t and "Talk needs an OpenAI key" in t
    assert "Arsenal v Spurs (active)" in t and "timeline" in t and "build one" in t


async def test_schedule_matches_the_scheduler(isolated_settings, tmp_path):
    from datetime import UTC, datetime

    from odie.app.main import start_scheduler
    s = Store(tmp_path / "b.db")
    s.init_schema()
    s.set_setting("news", {"fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": [], "items": []})  # no network
    from odie.background import Background
    sched = start_scheduler(s, runner=None, background=Background())
    try:
        assert {j.id for j in sched.get_jobs()} - {"news_now", "background_now"} == set(about.schedule())
    finally:
        sched.shutdown(wait=False)


def test_features_say_how_to_use_odie_on_a_phone(runner, monkeypatch):
    import dataclasses

    from odie import config, devices
    monkeypatch.setenv("ODIE_PAIRING", "on")
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, public_url="https://mac.example.ts.net"))
    devices.add_device(runner.store, "This Mac")
    t = about.features()
    phone = t[t.index("## Phone and other devices"):]
    assert "https://mac.example.ts.net" in phone and "Settings > Devices > Add a device" in phone and "QR code" in phone
    assert "Paired devices: 1" in phone and "Tailscale" in phone
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, public_url="http://localhost:8000"))
    assert "no phone address yet" in about.features() and "localhost" not in about.features()
