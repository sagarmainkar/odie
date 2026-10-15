import json

import pytest

from odie import voice
from odie.app.runner import claimed_but_not_done
from odie.store.db import Store
from tests.test_api import client  # noqa: F401  (fixture)


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_picking_an_openai_voice_keeps_the_openai_engine(tmp_path, monkeypatch):
    s = _store(tmp_path)
    monkeypatch.setattr(voice, "load_secret", lambda name: "sk-test")
    voice.set_tts(s, "openai", "coral")
    voice.set_voice(s, "coral")                     # what PUT /api/voice does next
    assert voice.get_tts(s) == ("openai", "coral")
    voice.set_tts(s, "kokoro", "hf_alpha")
    voice.set_voice(s, "cedar")                     # Talk's voice changes; read-aloud stays as chosen
    assert voice.get_tts(s) == ("kokoro", "hf_alpha") and voice.get_voice(s) == "cedar"


def test_a_kokoro_voice_on_a_fresh_store_is_kept(tmp_path, monkeypatch):
    s = _store(tmp_path)
    monkeypatch.setattr(voice, "load_secret", lambda name: None)
    assert voice.set_tts(s, voice="hf_alpha") == ("kokoro", "hf_alpha")


async def test_voice_route_round_trip(client, monkeypatch):
    monkeypatch.setattr(voice, "load_secret", lambda name: "sk-test")
    import odie.secrets as sec
    monkeypatch.setattr(sec, "load_secret", lambda name, env_file=None: "sk-test")
    c = client[0] if isinstance(client, tuple) else client
    assert (await c.put("/api/voice", json={"engine": "openai", "voice": "coral"})).json() == {"engine": "openai", "voice": "coral",
                                                                                              "reminders_spoken": False}
    j = (await c.get("/api/voice")).json()
    assert j["engine"] == "openai" and j["voice"] == "coral"


async def test_a_lapsed_approval_push_carries_no_details(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from odie.app import main
    s = _store(tmp_path)
    aid = s.create_approval("chat-2026-10-05", "inv", "req", "write_note", {"text": "private thought"},
                            "Write note in Obsidian notes: path: Inbox/idea.md; text: private thought",
                            {"app": "Obsidian notes"}, [], "normal")
    s.execute("update approvals set created_at=? where id=?", ((datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), aid))
    pushed = []
    monkeypatch.setattr("odie.push.send.send_to_all", lambda store, title, body, url="/", tag=None: pushed.append(body) or 1)
    await main.expire_approvals(s, None)
    assert pushed == ["Write note in Obsidian notes"]


@pytest.mark.parametrize("text, called, expected", [
    ("You have two tasks today. I'll remind you at 4 pm about the call.", {"task_list"}, None),   # describing one that exists
    ("I've set a reminder for 9 am.", {"task_update"}, None),
    ("I've set a reminder for 9 am.", set(), "task_add"),
])
def test_guard_does_not_nudge_after_listing(text, called, expected):
    assert claimed_but_not_done(text, called) == expected


async def test_readding_a_custom_provider_keeps_an_old_inline_key(client):
    c = client[0] if isinstance(client, tuple) else client
    st = c._transport.app.state.store
    st.set_setting("providers.custom", [{"id": "mine", "name": "Mine", "base_url": "https://x.example/v1", "api_key": "legacy-key"}])
    assert (await c.post("/api/models/providers", json={"name": "Mine", "base_url": "https://y.example/v1"})).status_code == 200
    from odie.models import all_providers
    assert {p.id: p for p in all_providers(st)}["mine"].api_key == "legacy-key"


# ── skills and plugins review ──
from odie import config
from odie.plugins import mcp
from odie.plugins.mcp import MASK, masked, unmask
from odie.skills import builder


@pytest.fixture
def bstore(isolated_settings, tmp_path):
    s = _store(tmp_path)

    async def reload():
        return {}
    builder.hooks.update(store=s, reload=reload, reserved=lambda: {})
    yield s
    builder.hooks.update(store=None, reload=None, reserved=None)


GOOD = 'from google.adk.tools import FunctionTool\n\n\nasync def hi() -> str:\n    """Hi."""\n    return "hi"\n\n\nTOOLS = [FunctionTool(hi)]\n'


async def test_updating_a_skill_keeps_its_other_files(bstore):
    d = config.settings.config_dir / "skills" / "travel"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: travel\ndescription: old\n---\nold")
    (d / "helper.py").write_text("X = 1\n")
    (d / "references" / "hotels.md").write_text("notes")
    out = await builder.draft("travel", "Plans trips.", "# Travel", GOOD, [])
    assert "replaces your travel skill" in out.lower() and "helper.py" in out
    assert "keeps" in builder.staged_text("travel").lower() or "helper.py" in builder.staged_text("travel")
    await builder.install("travel", builder.staged_version("travel"))
    assert (d / "helper.py").exists() and (d / "references" / "hotels.md").exists() and "Plans trips" in (d / "SKILL.md").read_text()


async def test_an_instructions_only_update_removes_old_code(bstore):
    d = config.settings.config_dir / "skills" / "notes"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: notes\ndescription: old\n---\nold")
    (d / "tools.py").write_text(GOOD)
    await builder.draft("notes", "Notes.", "# Notes", "", [])
    await builder.install("notes", builder.staged_version("notes"))
    assert not (d / "tools.py").exists()  # code the card didn't show must not stay behind, trusted


def test_masked_secrets_survive_edits():
    old = {"command": "npx", "args": ["-y", "srv", "--token", "t-999", "--api-key=k-1"], "env": {"GITHUB_TOKEN": "ghp_x"},
           "url": None}
    back = masked({k: v for k, v in old.items() if v is not None})
    back["args"] = back["args"] + ["--verbose"]                     # one more argument
    assert unmask(back, old)["args"] == ["-y", "srv", "--token", "t-999", "--api-key=k-1", "--verbose"]
    renamed = {**back, "env": {"GH_TOKEN": MASK}}
    with pytest.raises(ValueError, match="GH_TOKEN"):
        unmask(renamed, old)
    u_old = {"url": "https://api.example/mcp?api_key=abc&region=eu"}
    edited = {"url": masked(u_old)["url"].replace("region=eu", "region=us")}
    assert unmask(edited, u_old)["url"] == "https://api.example/mcp?api_key=abc&region=us"


async def test_editing_an_app_keeps_its_switches(isolated_settings, client):
    c = client[0] if isinstance(client, tuple) else client
    mcp.write_config({"gh": {"command": "npx", "args": ["-y", "srv"], "enabled": False, "alwaysOn": True, "note": "mine"}})
    r = await c.post("/api/mcp", json={"name": "gh", "spec": {"command": "npx", "args": ["-y", "srv"], "title": "GitHub", "env": {}}})
    assert r.status_code == 200
    saved = mcp.read_config()[0]["gh"]
    assert saved["enabled"] is False and saved["alwaysOn"] is True and saved["note"] == "mine" and saved["title"] == "GitHub"
    r = await c.post("/api/mcp", json={"name": "gh", "spec": {"url": "https://x.example/mcp", "headers": {}}})
    saved = mcp.read_config()[0]["gh"]
    assert saved["url"] == "https://x.example/mcp" and "command" not in saved and "args" not in saved  # switched kind


def test_tool_app_only_names_working_apps():
    mcp.TOOL_APP.clear()
    mcp._set_tool_apps([("Alpha", "ok", ["write_note"]), ("Beta", "error", ["write_note"])])
    assert mcp.TOOL_APP == {"write_note": "Alpha"}


def test_a_switched_off_skill_with_changed_code_reads_as_off(isolated_settings, tmp_path):
    from odie.skills.registry import discover
    s = _store(tmp_path)
    d = tmp_path / "user-skills" / "mine"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: mine\ndescription: Mine.\n---\nbody")
    (d / "tools.py").write_text(GOOD)
    s.set_setting("skills.disabled", ["mine"])
    e = next(e for e in discover(s, user_dir=tmp_path / "user-skills") if e.name == "mine")
    assert e.status == "disabled" and "OK" in e.reason


# ── trackers, up next, money review ──
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from odie import trackers as T
from odie import upcoming as U

IST = ZoneInfo("Asia/Kolkata")


def test_a_stop_during_a_check_is_not_undone(tmp_path):
    s = _store(tmp_path)
    t = T.create(s, "match", "score", "15m")
    row = T.get(s, t["id"])                  # the check starts with this snapshot
    T.set_status(s, t["id"], "stopped")      # The user taps Stop meanwhile
    T.record(s, row, T.parse_reply('```json\n{"state": "1-0", "summary": "x", "done": false, "met": false}\n```'), datetime.now(UTC), IST)
    assert T.get(s, t["id"])["status"] == "stopped"
    T.record_failure(s, row, datetime.now(UTC), IST)
    assert T.get(s, t["id"])["status"] == "stopped"


def test_until_means_the_end_of_that_day_in_india(tmp_path):
    s = _store(tmp_path)
    t = T.create(s, "x", "y", "1h", until="2026-10-20", tz=IST)
    assert datetime.fromisoformat(t["until_at"]) == datetime(2026, 10, 20, 23, 59, tzinfo=IST)


def test_check_now_and_the_schedule_never_run_together(tmp_path):
    s = _store(tmp_path)
    t = T.create(s, "x", "y", "15m")
    assert T.begin_check(t["id"]) is True and T.begin_check(t["id"]) is False   # a second start is refused
    assert t["id"] not in [r["id"] for r in T.due(s, datetime.now(UTC) + timedelta(minutes=1)) if T.begin_check(r["id"])]
    T.end_check(t["id"])
    assert T.begin_check(t["id"]) is True
    T.end_check(t["id"])


def _it(source, title, time=None, date="2026-10-10"):
    return {"id": f"{source}:{title}", "source": source, "kind": "general", "title": title, "date": date, "time": time,
            "end": None, "place": None, "people": None, "amount": None, "ask": ""}


def test_merge_needs_more_than_a_shared_time_or_word():
    assert len(U.merge([_it("calendar", "Yoga", "09:00"), _it("task", "Pay rent", "09:00")])) == 2
    assert len(U.merge([_it("calendar", "Call mom"), _it("task", "Call plumber")])) == 2
    assert len(U.merge([_it("calendar", "Dentist appointment", "10:00"), _it("mail", "Dentist visit", "10:00")])) == 1
    assert len(U.merge([_it("calendar", "Flight 6E 532"), _it("mail", "IndiGo 6E 532 Pune to Goa")])) == 1
