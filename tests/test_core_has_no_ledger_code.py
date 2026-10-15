"""The SMS ledger and Money are an add-on's: the core has no code, settings, routes, jobs, rules or
prefetch for them."""
import importlib.util

from odie import addons


def test_no_ledger_modules():
    for m in ("odie.money", "odie.jobs.sync", "odie.agent.tools.life_admin"):
        assert importlib.util.find_spec(m) is None, m


def test_no_ledger_setting(isolated_settings):
    assert not hasattr(isolated_settings, "msg_ledger_dir")


def test_no_money_routes():
    from odie.app.routes import router
    assert addons.active() == []
    assert not [r.path for r in router.routes if "/money" in getattr(r, "path", "")]


def test_no_ledger_rules_or_tools(isolated_settings, tmp_path):
    from odie.agent.agent import build_agent
    from odie.agent.prompt import ALL_CAPS, Who, rules_text
    from odie.store.db import Store
    text = rules_text(Who(caps=ALL_CAPS), gated=True)
    for word in ("life_admin", "SMS", "ledger"):
        assert word not in text, word
    s = Store(tmp_path / "a.db")
    s.init_schema()
    assert "life_admin" not in {getattr(t, "name", "") for t in build_agent(s).tools}


def test_no_ledger_prefetch():
    from odie.agent import prefetch
    assert not hasattr(prefetch, "LEDGER_OPEN") and not hasattr(prefetch, "search_ledger")


async def test_no_sync_job(isolated_settings, tmp_path):
    from datetime import UTC, datetime

    from odie.app.main import start_scheduler
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting("news", {"fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "topics": [], "items": []})
    sched = start_scheduler(s)
    try:
        assert sched.get_job("sync") is None
    finally:
        sched.shutdown(wait=False)
