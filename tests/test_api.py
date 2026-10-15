import json

import httpx
import pytest

from odie.app.main import create_app
from odie.store.db import Store


class FakeRunner:
    async def chat(self, text, thinking=False, session_id=None, images=None):
        for e in ({"type": "tool_start", "tool": "now", "args": {}}, {"type": "tool_done", "tool": "now"},
                  {"type": "token", "text": "It is "}, {"type": "text", "text": "It is 9:31."},
                  {"type": "done", "text": "It is 9:31."}):
            yield e

    async def history(self, date, limit=None, before=None):
        return {"items": [{"role": "user", "text": "hi", "tools": []}], "total": 1, "start": 0}

    async def post_message(self, text, session_id=None):
        self.posted = getattr(self, "posted", []) + [text]

    async def close(self):
        pass

    plugins = {"skills": [], "servers": []}

    async def load_plugins(self):
        return self.plugins


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json()["model"] and r.json()["name"] == "Odie"
    assert len(r.json()["version"]) == 7  # the short commit the app watches during an update


async def test_update_routes(client, monkeypatch):
    from odie import update
    assert (await client.get("/api/update")).status_code == 503  # the tests don't run from ~/.odie/app
    assert "update" not in (await client.get("/api/capabilities")).json()["caps"]
    monkeypatch.setattr(update, "can_update", lambda: True)
    assert "update" in (await client.get("/api/capabilities")).json()["caps"]

    async def check(force=False):
        return {"current": "aaaaaaa", "latest": "bbbbbbb", "behind": True, "checked_at": 1.0}
    monkeypatch.setattr(update, "check", check)
    monkeypatch.setattr(update, "running", lambda: False)
    monkeypatch.setattr(update, "start", lambda: 77)
    assert (await client.get("/api/update")).json() == {"current": "aaaaaaa", "latest": "bbbbbbb", "behind": True, "checked_at": 1.0, "running": False}
    assert (await client.post("/api/update")).json()["pid"] == 77
    monkeypatch.setattr(update, "running", lambda: True)
    assert (await client.post("/api/update")).status_code == 409


async def test_chat_sse(client):
    async with client.stream("POST", "/api/chat", json={"text": "time?"}) as r:
        body = "".join([chunk async for chunk in r.aiter_text()])
    assert "\r\n" not in body, "browser client splits on LF; server must not send CRLF"
    kinds = [json.loads(l[6:])["type"] for l in body.split("\n") if l.startswith("data: ")]
    assert kinds == ["tool_start", "tool_done", "token", "text", "done"]


async def test_history(client):
    r = await client.get("/api/history", params={"date": "2026-09-30"})
    assert r.json()["items"][0]["role"] == "user"


async def test_tasks_route(client):
    assert (await client.get("/api/tasks")).json() == []


async def test_subscribe_idempotent(client):
    sub = {"endpoint": "https://p/1", "keys": {"p256dh": "k", "auth": "a"}}
    assert (await client.post("/api/push/subscribe", json=sub)).json() == {"created": True}
    assert (await client.post("/api/push/subscribe", json=sub)).json() == {"created": False}


async def test_subscribe_rejects_bad_shape(client):
    assert (await client.post("/api/push/subscribe", json={"endpoint": "x"})).status_code == 422


async def test_push_test_route(client, monkeypatch):
    import odie.push.send as sendmod
    monkeypatch.setattr(sendmod, "send_to_all", lambda store, title, body, url="/", tag=None: 2)
    import odie.app.routes as routes  # the route imports inside the function, so patch the module it imports from
    assert (await client.post("/api/push/test")).json() == {"sent": 2}


async def test_brief_endpoint_returns_its_calendar_text(client):
    import json as _json
    c, store = client if isinstance(client, tuple) else (client, None)
    st = store or c._transport.app.state.store
    st.execute("insert into briefs(date, text, items_json) values(?,?,?)",
               ("2026-10-01", "Clear today.", _json.dumps({"calendar": "## 2026-10-02\nx | all day 2026-10-02 | Team offsite", "unread": "", "tasks": ""})))
    j = (await c.get("/api/brief")).json()
    assert j["text"] == "Clear today." and "Team offsite" in j["calendar"]


async def test_persona_routes(client):
    import io as _io
    from PIL import Image as _Image
    c = client[0] if isinstance(client, tuple) else client
    assert (await c.get("/api/persona")).json() == {"name": "Odie", "avatar_url": None}
    assert (await c.put("/api/persona", json={"name": "Mira"})).json()["name"] == "Mira"
    buf = _io.BytesIO(); _Image.new("RGB", (300, 400), (10, 20, 30)).save(buf, "JPEG")
    r = await c.post("/api/persona/avatar", files={"file": ("me.jpg", buf.getvalue(), "image/jpeg")})
    url = r.json()["avatar_url"]
    assert url.startswith("/api/persona/avatar/")
    got = await c.get(url)
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert (await c.post("/api/persona/avatar", files={"file": ("x.txt", b"not an image", "text/plain")})).status_code == 400
    assert (await c.delete("/api/persona/avatar")).json()["avatar_url"] is None


async def test_voice_routes_without_key(client, monkeypatch):
    import odie.secrets as sec
    monkeypatch.setattr(sec, "load_secret", lambda name, env_file=None: None)
    import odie.voice as v
    monkeypatch.setattr(v, "load_secret", lambda name: None)
    c = client[0] if isinstance(client, tuple) else client
    j = (await c.get("/api/voice")).json()
    assert j["available"] is False and j["engine"] == "kokoro" and j["voice"] == "af_heart" and len(j["voices"]) == 10
    async def fake_speak(store, text):
        return b"wav", "audio/wav"
    monkeypatch.setattr(v, "speak", fake_speak)  # no key: read-aloud is Kokoro (never the real local service in tests)
    assert (await c.post("/api/tts", json={"text": "hi"})).status_code == 200
    assert (await c.post("/api/stt", files={"file": ("a.webm", b"x", "audio/webm")})).status_code == 503  # dictation needs OpenAI
    assert (await c.put("/api/voice", json={"voice": "cedar"})).json()["voice"] == "af_heart"  # no OpenAI voices without its key


async def test_read_aloud_says_why_local_voice_is_off(client, monkeypatch, tmp_path):
    from odie import voice_worker
    from odie.voice_worker import VoiceWorker
    monkeypatch.setattr(voice_worker, "current", VoiceWorker(folder=tmp_path / "voice_server", port=1))  # no environment
    c = client[0] if isinstance(client, tuple) else client
    r = await c.post("/api/tts", json={"text": "hi"})  # Kokoro, the default without a key
    assert r.status_code == 503 and "uv sync" in r.json()["detail"]
    r = await c.get("/api/voice/preview/kokoro/af_heart")
    assert r.status_code == 503 and "uv sync" in r.json()["detail"]


def test_speakable_strips_markdown():
    from odie.app.routes import _speakable
    assert _speakable("**Due:** [Electricity](http://x) ₹2,480\n```code```") == "Due: Electricity ₹2,480"


async def test_voice_ask_refuses_empty_and_uses_a_voice_session(client):
    c = client[0] if isinstance(client, tuple) else client
    assert "didn't get a question" in (await c.post("/api/voice/ask", json={"question": " "})).json()["text"]


async def test_voice_transcript_posts_one_message(client):
    c = client[0] if isinstance(client, tuple) else client
    r = await c.post("/api/voice/transcript", json={"lines": [{"who": "you", "text": "What's due?"}, {"who": "odie", "text": "Electricity on the 12th."}]})
    assert r.json()["saved"] is True
    assert (await c.post("/api/voice/transcript", json={"lines": []})).json()["saved"] is False


def test_reply_preview_for_push():
    from odie.app.routes import reply_preview
    assert reply_preview("**Done.** Sent to Asha.\n\n```odie-chart\n{}\n```") == "Done. Sent to Asha."
    assert len(reply_preview("word " * 100)) <= 140



async def test_closed_today_route(client):
    r = await client.get("/api/tasks/closed_today")
    assert r.status_code == 200 and r.json() == {"count": 0}


async def test_news_route_empty(client):
    r = await client.get("/api/news")
    assert r.status_code == 200 and r.json()["items"] == []


async def test_news_refresh_route(client, monkeypatch):
    import odie.news.fetch as nf
    from odie.news.feeds import INDIA_TOPICS

    async def fake(store, transport=None, now=None):
        return {"fetched_at": "2026-10-05T06:00:00Z", "topics": INDIA_TOPICS, "items": [{"title": "t"}]}
    monkeypatch.setattr(nf, "refresh_news", fake)
    r = await client.post("/api/news/refresh")
    assert r.status_code == 200 and r.json()["items"] == [{"title": "t"}]


async def test_mcp_routes_mask_and_preserve_secrets(client, isolated_settings):
    from odie.plugins import mcp as m
    m.write_config({"gh": {"command": "npx", "args": ["x"], "env": {"TOKEN": "real-secret"}}})
    got = (await client.get("/api/mcp")).json()
    assert got["servers"][0]["spec"]["env"] == {"TOKEN": "••••"}
    spec = dict(got["servers"][0]["spec"], description="GitHub")  # save the masked form back unchanged
    r = await client.post("/api/mcp", json={"name": "gh", "spec": spec})
    assert r.status_code == 200 and m.read_config()[0]["gh"]["env"]["TOKEN"] == "real-secret"
    assert m.read_config()[0]["gh"]["description"] == "GitHub"


async def test_mcp_add_validates_and_delete_removes(client, isolated_settings):
    from odie.plugins import mcp as m
    assert (await client.post("/api/mcp", json={"name": "Bad Name", "spec": {"command": "x"}})).status_code == 422
    assert (await client.post("/api/mcp", json={"name": "ok", "spec": {}})).status_code == 422
    assert (await client.post("/api/mcp", json={"name": "ok", "spec": {"url": "http://h/mcp"}})).status_code == 200
    assert (await client.delete("/api/mcp/ok")).status_code == 200 and "ok" not in m.read_config()[0]


async def test_skill_routes_trust_and_switch(client, isolated_settings):
    d = isolated_settings.config_dir / "skills" / "greet"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: greet\ndescription: Say hi.\n---\nSay hi.\n")
    (d / "tools.py").write_text('async def hello() -> str:\n    """Hi."""\n    return "hi"\n\nTOOLS = [hello]\n')
    sk = {x["name"]: x for x in (await client.get("/api/skills")).json()["skills"]}
    assert sk["greet"]["status"] == "blocked" and sk["greet"]["source"] == "user"
    assert (await client.post("/api/skills/greet/trust")).status_code == 200
    assert {x["name"]: x for x in (await client.get("/api/skills")).json()["skills"]}["greet"]["status"] == "ok"
    await client.post("/api/skills/greet/enabled", json={"enabled": False})
    assert {x["name"]: x for x in (await client.get("/api/skills")).json()["skills"]}["greet"]["status"] == "disabled"


async def test_the_memory_row_shows_the_real_file(client):
    c = client[0] if isinstance(client, tuple) else client
    from odie import config
    got = (await c.get("/api/vault")).json()
    assert got["memory_file"] == str(config.settings.memory_file)


async def test_live_dictation_needs_openai_and_says_so(client, monkeypatch):
    from odie import voice
    c = client[0] if isinstance(client, tuple) else client
    monkeypatch.setattr(voice, "load_secret", lambda name: None)
    r = await c.post("/api/voice/dictation")
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]
    caps = (await c.get("/api/capabilities")).json()
    assert "dictation" not in caps["caps"]  # the phone picks its own dictation, or says what's missing, before you speak
    monkeypatch.setattr(voice, "load_secret", lambda name: "sk-test" if name == "OPENAI_API_KEY" else None)

    async def minted(key=None, transport=None):
        return {"client_secret": "ek_dict", "expires_at": 99}
    monkeypatch.setattr(voice, "dictation_session", minted)
    assert (await c.post("/api/voice/dictation")).json() == {"client_secret": "ek_dict", "expires_at": 99}
    caps = (await c.get("/api/capabilities")).json()
    assert "dictation" in caps["caps"] and caps["country"] == __import__("odie.config", fromlist=["settings"]).settings.country
    assert "talk" not in caps["caps"]  # Talk is held back for now, key or no key
    assert (await c.post("/api/voice/session")).status_code == 503
