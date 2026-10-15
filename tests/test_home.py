import importlib
import stat
from pathlib import Path

import pytest

from odie import home


@pytest.fixture
def bare_env(monkeypatch):
    for k in ("ODIE_HOME", "ODIE_DATA_DIR", "ODIE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)


def test_everything_lives_in_one_folder(bare_env, tmp_path):
    assert home.resolve(tmp_path) == home.Layout(tmp_path / ".odie", tmp_path / ".odie" / "data", tmp_path / ".odie")


def test_odie_home_moves_everything(bare_env, tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_HOME", str(tmp_path / "elsewhere"))
    lay = home.resolve(tmp_path)
    assert lay == home.Layout(tmp_path / "elsewhere", tmp_path / "elsewhere" / "data", tmp_path / "elsewhere")


def test_explicit_folders_stand_alone(bare_env, tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("ODIE_CONFIG_DIR", str(tmp_path / "c"))
    assert home.resolve(tmp_path) == home.Layout(None, tmp_path / "d", tmp_path / "c")  # no real ~/.odie


def test_home_folder_is_private(tmp_path):
    lay = home.Layout(tmp_path / ".odie", tmp_path / ".odie" / "data", tmp_path / ".odie")
    home.ensure(lay)
    assert stat.S_IMODE((tmp_path / ".odie").stat().st_mode) == 0o700 and lay.data_dir.is_dir()


@pytest.fixture
def fresh_config(monkeypatch, tmp_path):
    """Settings rebuilt from this test's environment and .env; restored afterwards."""
    import odie.config as c
    monkeypatch.setenv("ODIE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ODIE_CONFIG_DIR", str(tmp_path / "config"))
    for k in ("ODIE_MEMORY_FILE", "ODIE_PORT", "LM_STUDIO_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "config").mkdir()
    yield lambda: importlib.reload(c).settings
    monkeypatch.undo()
    importlib.reload(c)


def test_settings_read_from_the_env_file(fresh_config, tmp_path, monkeypatch):
    (tmp_path / "config" / ".env").write_text(
        'OPENAI_API_KEY=x\nexport ODIE_MEMORY_FILE="~/notes/m.md"\nODIE_PORT=8123\nODIE_PORT=8124\nLM_STUDIO_BASE_URL=http://127.0.0.1:1235/v1\n')
    s = fresh_config()
    assert s.memory_file == Path("~/notes/m.md").expanduser() and s.port == 8123  # the first line wins, like the keys
    assert s.lm_studio_base_url == "http://127.0.0.1:1235/v1"  # a setting without the ODIE_ prefix
    monkeypatch.setenv("ODIE_PORT", "9000")
    assert fresh_config().port == 9000  # the environment wins over the file


def test_memory_defaults_into_the_data_folder_of_a_test_copy(fresh_config, tmp_path):
    assert fresh_config().memory_file == tmp_path / "data" / "memories.md"


def test_tests_never_see_the_real_folders():
    from odie import config
    s = config.settings
    real = [Path.home() / p for p in (".odie", "vault")]
    for p in (s.data_dir, s.config_dir, s.memory_file):
        assert not any(p == r or r in p.parents for r in real), p
