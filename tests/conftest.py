import importlib
import os
import tempfile
from pathlib import Path

import pytest

# Before anything imports odie.config: the settings every test starts with point at a throwaway folder, never a real
# ~/.odie (settings are read from the .env in that folder too).
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="odie-tests-"))
os.environ.pop("ODIE_HOME", None)
for _key, _sub in (("ODIE_DATA_DIR", "data"), ("ODIE_CONFIG_DIR", "config"), ("ODIE_MEMORY_FILE", "memories.md")):
    os.environ[_key] = str(_TEST_ROOT / _sub)
os.environ["ODIE_ADDONS"] = ""  # no add-ons unless a test brings its own: never a real home's
os.environ["MSG_LEDGER_DIR"] = str(_TEST_ROOT / "no-ledger")  # never the real SMS ledger (the personal add-on reads it)
os.environ["ODIE_PAIRING"] = "off"  # every API open (the pairing tests turn it on)
os.environ["ODIE_BROWSER"] = "off"  # the same prompt and tools on every machine (browser tests find one themselves)
os.environ["ODIE_KEYCHAIN"] = str(_TEST_ROOT / "no-keychain.keychain-db")  # never the login keychain: a stray vault call fails
os.environ.setdefault("ODIE_TIMEZONE", "Asia/Kolkata")  # the region the existing tests were written in
os.environ.setdefault("ODIE_LOCALE", "en-IN")


# Tests that need a Mac with Odie built on it, not GitHub's bare runner: the voice and embedding workers' own
# environments (`uv sync` in voice_server and embed_server), the embedding model, and a Photos library.
# On the runner (GITHUB_ACTIONS=true) they are skipped with this reason; on the owner's Mac they run.
# Each entry: file -> (the part(s) of the test's name it applies to, or "" for the whole file; why).
# Worked example: test_photos_odie.py::test_the_worker_reads_the_library on the runner -> skipped;
# test_photos_odie.py::test_search_only_photos on the runner -> runs; both run on this Mac.
THIS_MAC_ONLY = {
    "test_voice_worker.py": ("", "starts the voice worker's own environment (uv sync in voice_server)"),
    "test_embed_server.py": ("", "the embedding service answers 503 until the model is on disk"),
    "test_photos_odie.py": (("worker", "switching_photos_off"), "the vault worker needs the embedding worker's environment"),
    "test_pictures_meaning.py": ("worker", "reads pictures by meaning with the embedding worker's environment"),
}


def pytest_collection_modifyitems(items):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for item in items:
        entry = THIS_MAC_ONLY.get(Path(str(item.fspath)).name)
        if entry is None:
            continue
        name_parts, reason = entry
        if isinstance(name_parts, str):
            name_parts = (name_parts,)
        if any(part in item.name for part in name_parts):
            item.add_marker(pytest.mark.skip(reason=f"only on a Mac with Odie built: {reason}"))

@pytest.fixture(autouse=True)
def no_model_probe(monkeypatch):
    """Tests never ask the real LM Studio or Ollama for a model's context size (a test that needs one patches it)."""
    async def unknown(sel, transport=None):
        return None
    import odie.app.runner as runner_mod
    monkeypatch.setattr(runner_mod, "context_window", unknown)


@pytest.fixture(autouse=True)
def no_fallback_probe(monkeypatch):
    """Tests never ask the real LM Studio or Ollama which models they have when Odie works out its fallback model:
    neither answers (a test that needs one patches odie.models.ask_local_providers)."""
    async def nobody_answers(transport=None):
        return [{"id": pid, "name": pid, "local": True, "models": [], "error": "ConnectError"} for pid in ("lmstudio", "ollama")]
    import odie.models as models_mod
    monkeypatch.setattr(models_mod, "ask_local_providers", nobody_answers)


@pytest.fixture(autouse=True)
def no_real_secrets(tmp_path, monkeypatch):
    """Keys are read from and written to <ODIE_CONFIG_DIR>/.env: every test gets its own, never ~/.odie/.env."""
    monkeypatch.setenv("ODIE_CONFIG_DIR", str(tmp_path / "config"))


@pytest.fixture(autouse=True)
def no_tracing(monkeypatch):
    """Tests never send traces to LangSmith, even though the real key is in ~/.odie/.env."""
    monkeypatch.setenv("ODIE_TRACE", "0")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Point the data and settings folders at tmp and reload config so nothing touches the real ones."""
    monkeypatch.setenv("ODIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ODIE_CONFIG_DIR", str(tmp_path / "config"))  # never the real settings folder
    monkeypatch.setenv("ODIE_MEMORY_FILE", str(tmp_path / "odie-memories.md"))
    monkeypatch.setenv("ODIE_PREFETCH", "0")  # never reach the real vault or SMS ledger from tests
    import odie.config as c
    importlib.reload(c)
    yield c.settings
    monkeypatch.undo()  # back to this session's throwaway folders (set at the top of this file)
    importlib.reload(c)


@pytest.fixture
def keychain(tmp_path, monkeypatch):
    """A throwaway keychain for the vault (security create-keychain doesn't add it to the search list)."""
    import shutil
    import subprocess
    if shutil.which("security") is None:
        pytest.skip("no macOS security tool here")
    k = tmp_path / "test.keychain-db"
    subprocess.run(["security", "create-keychain", "-p", "test", str(k)], check=True, capture_output=True)
    subprocess.run(["security", "unlock-keychain", "-p", "test", str(k)], check=True, capture_output=True)
    subprocess.run(["security", "set-keychain-settings", str(k)], check=True, capture_output=True)  # never locks: a locked one prompts on screen
    monkeypatch.setenv("ODIE_KEYCHAIN", str(k))
    assert str(k).startswith(str(tmp_path)) and "login.keychain" not in str(k)
    yield k
    subprocess.run(["security", "delete-keychain", str(k)], capture_output=True)


@pytest.fixture(autouse=True)
def fresh_signin_boxes():
    from odie.agent.tools import browser as browser_tools
    from odie.signin import box, guard
    box._boxes.clear()
    browser_tools._carded.clear()
    guard.READ.clear()  # the signed-in pages a chat read (a tracker's page comes from here)
    yield
    box._boxes.clear()
    browser_tools._carded.clear()
    guard.READ.clear()


@pytest.fixture(autouse=True)
def no_mac_apps(monkeypatch):
    """No test drives the developer's own Mail, Calendar, Reminders or Contacts: the AppleScript runner refuses, and
    the watch finds no Mac sources. A test of those paths passes its own fakes (odie.mac.* take `run=`;
    odie.watch.sources.native_sources takes `available=` and `status=`)."""
    from odie.mac import scripts
    from odie.watch import sources
    monkeypatch.setattr(scripts, "ALLOWED", False)
    monkeypatch.setattr(scripts, "available", lambda: False)  # routes and setup see "not a Mac" unless a test says so
    monkeypatch.setattr(sources, "native_sources", lambda available=None, status=None: [])
