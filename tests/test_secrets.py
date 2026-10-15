from odie.secrets import load_secret


def test_reads_env_file_and_env_wins(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# keys\nexport OPENAI_API_KEY='sk-file'\nOTHER=x\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert load_secret("OPENAI_API_KEY", f) == "sk-file"
    assert load_secret("MISSING", f) is None
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert load_secret("OPENAI_API_KEY", f) == "sk-env"
    assert load_secret("OPENAI_API_KEY", tmp_path / "nope") == "sk-env"


def test_quoted_values_keep_their_spaces(tmp_path, monkeypatch):
    """A quoted path with spaces (an iCloud vault: ".../Mobile Documents/...") is read whole, not cut at the space."""
    from odie.secrets import load_secret
    for k in ("ODIE_MEMORY_FILE", "ODIE_X", "ODIE_Y", "ODIE_Z"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text('ODIE_MEMORY_FILE="/Users/a/Library/Mobile Documents/vault/m.md"\n'
                   "export ODIE_X='two words'\nODIE_Y=plain # a comment\nODIE_Z=\"\"\n")
    assert load_secret("ODIE_MEMORY_FILE", env) == "/Users/a/Library/Mobile Documents/vault/m.md"
    assert load_secret("ODIE_X", env) == "two words"
    assert load_secret("ODIE_Y", env) == "plain"
    assert load_secret("ODIE_Z", env) is None
