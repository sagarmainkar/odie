"""odie.machine: which of Odie's own services this machine is meant to run, by ODIE_VOICE (on unless switched off)
and ODIE_EMBED (off unless switched on, since 25 Oct 2026: Ollama's EmbeddingGemma 2 does the job without a download)."""
from odie import machine


def test_the_voice_switch_reads_the_installers_words(monkeypatch):
    for word in ("off", "0", "no", " OFF "):
        monkeypatch.setenv("ODIE_VOICE", word)
        assert machine.local_voice_wanted() is False, word
    for word in ("", "on", "yes", "anything"):
        monkeypatch.setenv("ODIE_VOICE", word)
        assert machine.local_voice_wanted() is True, word


def test_the_embedding_switch_is_opt_in(monkeypatch):
    for word in ("on", "1", "yes", " ON "):
        monkeypatch.setenv("ODIE_EMBED", word)
        assert machine.local_embeddings_wanted() is True, word
    for word in ("", "off", "0", "no", "anything"):
        monkeypatch.setenv("ODIE_EMBED", word)
        assert machine.local_embeddings_wanted() is False, word


def test_unset_means_voice_on_and_embeddings_off(monkeypatch):
    monkeypatch.delenv("ODIE_VOICE", raising=False)
    monkeypatch.delenv("ODIE_EMBED", raising=False)
    assert machine.local_voice_wanted() is True and machine.local_embeddings_wanted() is False


def test_the_two_switches_are_separate(monkeypatch):
    monkeypatch.setenv("ODIE_VOICE", "off")
    monkeypatch.setenv("ODIE_EMBED", "on")
    assert machine.local_voice_wanted() is False and machine.local_embeddings_wanted() is True
