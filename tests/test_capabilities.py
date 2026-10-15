import importlib
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def detect_with(isolated_settings, monkeypatch, tmp_path):
    """Capabilities for a temporary install that has the given pieces."""
    import odie.config as c

    def make(gmail=False, ledger=False, vault=False, vault_status="ok"):
        entry = tmp_path / "gmail" / "index.ts"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("") if gmail else entry.unlink(missing_ok=True)
        ledger_dir = tmp_path / "ledger"
        if ledger:
            ledger_dir.mkdir(exist_ok=True)
        elif ledger_dir.exists():
            ledger_dir.rmdir()
        monkeypatch.setenv("GMAIL_MCP_ENTRY", str(entry))
        monkeypatch.setenv("MSG_LEDGER_DIR", str(ledger_dir))
        monkeypatch.delenv("ODIE_MOCK_MCP", raising=False)
        (tmp_path / "config").mkdir(exist_ok=True)
        servers = {"vault": {"url": "http://127.0.0.1:9/mcp"}} if vault else {}
        (tmp_path / "config" / "mcp.json").write_text(json.dumps({"mcpServers": servers}))
        importlib.reload(c)
        from odie import capabilities
        loaded = [SimpleNamespace(name="vault", status=vault_status)] if vault else []
        return capabilities.detect(loaded)
    return make


def test_nothing_connected(detect_with):
    assert detect_with() == frozenset()


def test_everything_connected(detect_with):
    assert detect_with(gmail=True, ledger=True, vault=True) == frozenset({"vault"})  # mail and money are an add-on's


def test_each_piece_on_its_own(detect_with):
    assert detect_with(gmail=True) == frozenset()  # the core doesn't know any mail server
    assert detect_with(ledger=True) == frozenset()  # the core doesn't know msg-ledger
    assert detect_with(vault=True) == frozenset({"vault"})


def test_vault_needs_a_server_that_loaded(detect_with):
    """mcp.json lists the vault on every install (written on first run); only a server that answered counts."""
    assert detect_with(vault=True, vault_status="failed") == frozenset()
    assert detect_with(vault=True, vault_status="disabled") == frozenset()
