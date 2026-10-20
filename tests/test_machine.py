"""odie.machine: which of Odie's own services this machine is meant to run, by ODIE_VOICE and ODIE_EMBED."""
from odie import machine


def test_the_switches_read_the_installers_words(monkeypatch):
    for word in ("off", "0", "no", " OFF "):
        monkeypatch.setenv("ODIE_VOICE", word)
        monkeypatch.setenv("ODIE_EMBED", word)
        assert machine.local_voice_wanted() is False and machine.local_embeddings_wanted() is False, word
    for word in ("", "on", "yes", "anything"):
        monkeypatch.setenv("ODIE_VOICE", word)
        monkeypatch.setenv("ODIE_EMBED", word)
        assert machine.local_voice_wanted() is True and machine.local_embeddings_wanted() is True, word


def test_unset_means_on(monkeypatch):
    monkeypatch.delenv("ODIE_VOICE", raising=False)
    monkeypatch.delenv("ODIE_EMBED", raising=False)
    assert machine.local_voice_wanted() is True and machine.local_embeddings_wanted() is True


def test_the_two_switches_are_separate(monkeypatch):
    monkeypatch.setenv("ODIE_VOICE", "off")
    monkeypatch.delenv("ODIE_EMBED", raising=False)
    assert machine.local_voice_wanted() is False and machine.local_embeddings_wanted() is True
