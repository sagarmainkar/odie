"""The add-on loader: folders on the add-ons path, each a package whose register(odie) returns an Addon."""
import importlib
import textwrap

import httpx
import pytest

from odie import addons
from odie.addons import Addon


@pytest.fixture(autouse=True)
def no_addons_after():
    yield
    addons.use(None)


@pytest.fixture
def bare(isolated_settings, monkeypatch, tmp_path):
    """An install with nothing of its own beyond the core (this computer may have add-ons of its own)."""
    import odie.config as c
    monkeypatch.setenv("GMAIL_MCP_ENTRY", str(tmp_path / "no-gmail" / "index.ts"))
    monkeypatch.setenv("MSG_LEDGER_DIR", str(tmp_path / "no-ledger"))
    monkeypatch.delenv("ODIE_MOCK_MCP", raising=False)
    importlib.reload(c)
    return c.settings


def make(root, name, body):
    d = root / name
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(textwrap.dedent(body))
    return d


GOOD = """
    def register(odie):
        return odie.Addon(name="{name}", tool_names=frozenset({{"{tool}"}}))
"""


def test_loads_a_registered_addon(tmp_path):
    make(tmp_path, "greet", """
        from .words import HELLO

        def register(odie):
            return odie.Addon(name="greet", capabilities=lambda: frozenset({HELLO}))
    """)
    (tmp_path / "greet" / "words.py").write_text('HELLO = "hello"\n')
    [f] = addons.load([tmp_path])
    assert (f.name, f.status, f.reason) == ("greet", "ok", "")
    assert isinstance(f.addon, Addon) and f.addon.capabilities() == frozenset({"hello"})


def test_folder_without_init_is_skipped(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "README.md").write_text("not an add-on")
    assert addons.load([tmp_path, tmp_path / "missing"]) == []


def test_bad_folder_name_is_refused(tmp_path):
    make(tmp_path, "Bad-Name", GOOD.format(name="Bad-Name", tool="t"))
    [f] = addons.load([tmp_path])
    assert f.status == "failed" and "lower-case" in f.reason


def test_broken_addon_is_reported_not_fatal(tmp_path):
    make(tmp_path, "a_import", "raise ImportError('no such module: mlx')\n")
    make(tmp_path, "b_register", """
        def register(odie):
            raise RuntimeError("needs a key")
    """)
    make(tmp_path, "c_wrong", """
        def register(odie):
            return {"name": "c_wrong"}
    """)
    make(tmp_path, "d_noregister", "X = 1\n")
    make(tmp_path, "e_misnamed", GOOD.format(name="other", tool="t1"))
    make(tmp_path, "f_good", GOOD.format(name="f_good", tool="t2"))
    got = {f.name: f for f in addons.load([tmp_path])}
    assert {n: f.status for n, f in got.items()} == {"a_import": "failed", "b_register": "failed", "c_wrong": "failed",
                                                      "d_noregister": "failed", "e_misnamed": "failed", "f_good": "ok"}
    assert "mlx" in got["a_import"].reason and "needs a key" in got["b_register"].reason
    assert "Addon" in got["c_wrong"].reason and "register" in got["d_noregister"].reason
    assert "e_misnamed" in got["e_misnamed"].reason
    assert all("\n" not in f.reason for f in got.values())


def test_duplicate_names_are_refused(tmp_path):
    make(tmp_path / "one", "mail", GOOD.format(name="mail", tool="send"))
    make(tmp_path / "two", "mail", GOOD.format(name="mail", tool="other"))
    make(tmp_path / "two", "post", GOOD.format(name="post", tool="send"))
    got = addons.load([tmp_path / "one", tmp_path / "two"])
    assert [(f.name, f.status) for f in got] == [("mail", "ok"), ("mail", "failed"), ("post", "failed")]
    assert "already loaded" in got[1].reason and "clash with mail" in got[2].reason


def test_addons_path_from_settings(monkeypatch, tmp_path):
    import odie.config as c
    monkeypatch.setenv("ODIE_ADDONS", f"{tmp_path / 'a'}::{tmp_path / 'b'}")
    importlib.reload(c)
    assert c.settings.addons_dirs == [tmp_path / "a", tmp_path / "b"]
    monkeypatch.delenv("ODIE_ADDONS")
    monkeypatch.delenv("ODIE_DATA_DIR")
    monkeypatch.delenv("ODIE_CONFIG_DIR")
    monkeypatch.setenv("ODIE_HOME", str(tmp_path / "home"))
    importlib.reload(c)
    assert c.settings.addons_dirs == [tmp_path / "home" / "addons"]
    monkeypatch.undo()
    importlib.reload(c)
    assert c.settings.addons_dirs == []  # the test session's own setting: never a real home's add-ons


def test_capabilities_include_addons(bare):
    from odie import capabilities
    addons.use([Addon("x", capabilities=lambda: frozenset({"mail"}))])
    assert "mail" in capabilities.detect([])
    addons.use([])
    assert "mail" not in capabilities.detect([])


def test_call_skips_a_raising_hook():
    def boom():
        raise ValueError("broken")
    addons.use([Addon("a", capabilities=boom), Addon("b", capabilities=lambda: frozenset({"calendar"}))])
    assert addons.call("capabilities") == [frozenset({"calendar"})]
    assert addons.capabilities() == frozenset({"calendar"})


async def test_acall_skips_a_raising_hook():
    async def ok(store, now, post):
        return ["part"]

    async def bad(store, now, post):
        raise RuntimeError("calendar down")
    addons.use([Addon("a", brief=bad), Addon("b", brief=ok), Addon("c")])
    assert await addons.acall("brief", None, None, None) == [["part"]]


def test_gated_and_tool_names_and_rules():
    from odie.agent.prompt import Rule
    r = Rule("- a rule")
    addons.use([Addon("a", tool_names=frozenset({"x", "y"}), gated=frozenset({"y"}), rules=[r]), Addon("b")])
    assert addons.gated_tools() == frozenset({"y"}) and addons.tool_names() == frozenset({"x", "y"})
    assert addons.rules() == [r]


def test_found_loads_from_the_settings_path_once(isolated_settings, monkeypatch, tmp_path):
    import odie.config as c
    make(tmp_path / "ad", "greet", GOOD.format(name="greet", tool="t"))
    monkeypatch.setenv("ODIE_ADDONS", str(tmp_path / "ad"))
    importlib.reload(c)
    addons.use(None)
    assert [a.name for a in addons.active()] == ["greet"]
    assert addons.found() is addons.found()


async def test_capabilities_route(bare, tmp_path):
    from odie.app.main import create_app
    from odie.store.db import Store
    from tests.test_api import FakeRunner
    make(tmp_path / "ad", "broken", "raise ImportError('missing dependency')\n")
    make(tmp_path / "ad", "mailer", """
        def register(odie):
            return odie.Addon(name="mailer", capabilities=lambda: frozenset({"mail", "calendar"}))
    """)
    addons.use(None)
    addons._found = addons.load([tmp_path / "ad"])
    s = Store(tmp_path / "a.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        async with app.router.lifespan_context(app):
            r = await client.get("/api/capabilities")
    body = r.json()
    assert body["caps"] == ["calendar", "mail"]
    assert body["addons"] == [{"name": "broken", "status": "failed", "reason": body["addons"][0]["reason"]},
                              {"name": "mailer", "status": "ok", "reason": ""}]
    assert "missing dependency" in body["addons"][0]["reason"]


def test_an_empty_addons_setting_means_none(monkeypatch, tmp_path):
    """ODIE_ADDONS= switches add-ons off, even for an install with a home (whose addons folder would be the default)."""
    import odie.config as c
    for k in ("ODIE_DATA_DIR", "ODIE_CONFIG_DIR"):
        monkeypatch.delenv(k)
    monkeypatch.setenv("ODIE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ODIE_ADDONS", "")
    try:
        assert importlib.reload(c).settings.addons_dirs == []
    finally:
        monkeypatch.undo()
        importlib.reload(c)


def test_malformed_declarations_fail_the_addon(tmp_path):
    make(tmp_path, "bad_cron", """
        async def run(store, runner):
            pass

        def register(odie):
            return odie.Addon(name="bad_cron", jobs=[odie.Job("x", run, {"minute": "every so often"}, "x")])
    """)
    make(tmp_path, "bad_job", """
        def register(odie):
            return odie.Addon(name="bad_job", jobs=["sync at noon"])
    """)
    make(tmp_path, "bad_router", """
        def register(odie):
            return odie.Addon(name="bad_router", router="nope")
    """)
    make(tmp_path, "bad_rule", """
        def register(odie):
            return odie.Addon(name="bad_rule", rules=["- not a Rule"])
    """)
    got = {f.name: f for f in addons.load([tmp_path])}
    assert {n: f.status for n, f in got.items()} == {n: "failed" for n in ("bad_cron", "bad_job", "bad_router", "bad_rule")}
    assert "minute" in got["bad_cron"].reason and "Job" in got["bad_job"].reason
    assert "router" in got["bad_router"].reason and "Rule" in got["bad_rule"].reason


def test_an_unreadable_folder_on_the_path_is_skipped(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    make(tmp_path / "ok", "greet", GOOD.format(name="greet", tool="t"))
    locked.chmod(0)
    try:
        assert [f.name for f in addons.load([locked, tmp_path / "ok"])] == ["greet"]
    finally:
        locked.chmod(0o755)
