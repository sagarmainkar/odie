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
