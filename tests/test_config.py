import importlib


def test_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("ODIE_DATA_DIR", str(tmp_path))
    import odie.config as c
    importlib.reload(c)
    s = c.settings
    assert s.data_dir == tmp_path
    assert s.db_path == tmp_path / "assistant.db"
    assert s.model_id == "gemma-4-26b-a4b-it-qat"
    assert s.lm_studio_base_url.endswith("/v1")
    assert s.timezone == "Asia/Kolkata"


def test_a_phone_address_learned_after_start_is_used_until_the_env_has_one(monkeypatch):
    import dataclasses
    from odie import config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, public_url="http://localhost:8000"))
    monkeypatch.setattr(config, "learned_public_url", "")
    assert config.phone_address() == ""
    config.learn_public_url("https://mac.example.ts.net/")
    assert config.phone_address() == "https://mac.example.ts.net"
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, public_url="https://other.example.ts.net"))
    assert config.phone_address() == "https://other.example.ts.net"  # the service's own setting wins
