"""Mail, Calendar and the Google sign-in are an add-on's: the core has no code, settings, routes,
jobs or prompt rules for them."""
import importlib.util

from odie import addons


def test_no_mail_modules():
    for m in ("odie.google", "odie.agent.toolsets", "odie.jobs.inbox", "odie.jobs.mcp_call"):
        assert importlib.util.find_spec(m) is None, m


def test_no_mail_settings(isolated_settings):
    for f in ("gmail_mcp_entry", "gmail_account", "obsidian_rag_url", "obsidian_profile"):
        assert not hasattr(isolated_settings, f), f


def test_no_google_routes(isolated_settings, tmp_path):
    from odie.app.routes import router
    assert addons.active() == []
    assert not [r.path for r in router.routes if "/google" in getattr(r, "path", "")]


def test_no_mail_rules():
    from odie.agent.prompt import ALL_CAPS, Who, rules_text
    text = rules_text(Who(caps=ALL_CAPS), gated=True)
    for word in ("gmail", "calendar_list_events", "Connect Google"):
        assert word not in text, word


async def test_no_mail_jobs(isolated_settings, tmp_path):
    from datetime import UTC, datetime

    from odie.app.main import start_scheduler
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting("news", {"fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": [], "items": []})
    sched = start_scheduler(s)
    try:
        assert not {"inbox", "mail_events", "google_expiry"} & {j.id for j in sched.get_jobs()}
    finally:
        sched.shutdown(wait=False)
