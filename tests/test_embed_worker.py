"""The embedding service's process manager: the voice worker's, pointed at embed_server/ (its own title, port and log),
with the Hugging Face token passed through for the gated model."""
from odie import embed_worker
from odie.voice_worker import VoiceWorker


def test_the_embed_worker_is_a_local_worker_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_EMBED_PORT", "8990")
    w = embed_worker.EmbedWorker(folder=tmp_path)
    assert isinstance(w, VoiceWorker)
    assert w.title == "odie-embed" and w.port == 8990 and w.url == "http://127.0.0.1:8990"
    assert w.what == "local embeddings"
    assert not w.installed  # no .venv in tmp_path
    assert w.cmd[1:] == ["server:app", "--host", "127.0.0.1", "--port", "8990"]


def test_the_default_port_sits_next_to_the_voice_workers(monkeypatch):
    monkeypatch.delenv("ODIE_EMBED_PORT", raising=False)
    assert embed_worker.embed_port() == 8772


def test_the_hugging_face_token_reaches_the_service(monkeypatch):
    monkeypatch.setattr(embed_worker, "load_secret", lambda name: "hf_abc" if name == "HF_TOKEN" else None)
    assert embed_worker.EmbedWorker().environment()["HF_TOKEN"] == "hf_abc"
    monkeypatch.setattr(embed_worker, "load_secret", lambda name: None)
    assert "HF_TOKEN" not in embed_worker.EmbedWorker().environment()


def test_the_idle_minutes_come_from_odies_settings(isolated_settings, monkeypatch):
    """ODIE_EMBED_IDLE_MINUTES in ~/.odie/.env (or the environment) reaches the service; 15 when unset."""
    import importlib

    import odie.config as c
    monkeypatch.setattr(embed_worker, "load_secret", lambda name: None)
    assert embed_worker.EmbedWorker().environment() == {"ODIE_EMBED_IDLE_MINUTES": "15"}
    monkeypatch.setenv("ODIE_EMBED_IDLE_MINUTES", "30")
    importlib.reload(c)
    assert embed_worker.EmbedWorker().environment() == {"ODIE_EMBED_IDLE_MINUTES": "30"}
