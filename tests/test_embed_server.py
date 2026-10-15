"""Odie's own embedding service (embed_server/server.py): EmbeddingGemma 2 on this Mac, behind the same request shape
OpenAI's embeddings API has, plus `kind` (query or document) so the service adds Gemma's own prefixes. Tested here
with a fake encoder, so the suite never loads the model."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "embed_server"))
import server  # noqa: E402  (embed_server/server.py; torch and the model load lazily, never here)


def test_gemma_prefixes_queries_and_documents_differently():
    assert server.prefixed(["what causes northern lights?"], "query") == ["task: search result | query: what causes northern lights?"]
    assert server.prefixed(["Charged particles from the sun."], "document") == ["title: none | text: Charged particles from the sun."]
    with pytest.raises(ValueError):
        server.prefixed(["x"], "picture")


def test_the_response_has_openais_shape_with_unit_vectors(monkeypatch):
    seen = []

    def fake_encode(texts):
        seen.append(texts)
        return [[3.0, 4.0, 0.0] for _ in texts]
    monkeypatch.setattr(server, "_encode", fake_encode)
    c = TestClient(server.app)
    r = c.post("/v1/embeddings", json={"input": ["a", "b"], "kind": "query"})
    assert r.status_code == 200
    d = r.json()
    assert d["model"] == server.MODEL and [x["index"] for x in d["data"]] == [0, 1]
    assert d["data"][0]["embedding"] == pytest.approx([0.6, 0.8, 0.0])  # normalised
    assert seen == [["task: search result | query: a", "task: search result | query: b"]]
    assert d["usage"]["prompt_tokens"] > 0


def test_a_single_string_and_the_default_kind_are_documents(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "_encode", lambda texts: (seen.append(texts) or [[1.0, 0.0]] * len(texts)))
    c = TestClient(server.app)
    assert c.post("/v1/embeddings", json={"input": "one note"}).status_code == 200
    assert seen == [["title: none | text: one note"]]
    assert c.post("/v1/embeddings", json={"input": [], "kind": "query"}).status_code == 400
    assert c.post("/v1/embeddings", json={"input": ["x"], "kind": "picture"}).status_code == 400


def test_health_says_which_model_and_whether_it_is_loaded():
    c = TestClient(server.app)
    d = c.get("/health").json()
    assert d["ok"] is True and d["model"] == server.MODEL and d["dims"] == 768 and d["loaded"] is False
    assert d["idle_minutes"] == 15  # the default; ODIE_EMBED_IDLE_MINUTES in ~/.odie/.env changes it
    assert c.get("/openapi.json").json()["info"]["title"] == "odie-embed"


def test_the_model_is_unloaded_after_a_quiet_spell():
    """Fifteen minutes without a request (the default) and the model's memory goes back; 0 keeps it loaded."""
    now = 1_000_000.0
    assert server.should_unload(True, now - 20 * 60, now, 15) is True
    assert server.should_unload(True, now - 5 * 60, now, 15) is False
    assert server.should_unload(True, now - 20 * 60, now, 0) is False   # never
    assert server.should_unload(False, now - 20 * 60, now, 15) is False  # nothing loaded


# ── pictures (2026-10-14): one vector per picture from its words and its pixels together ──
def test_a_document_may_carry_its_real_title():
    assert server.prefixed([{"title": "Trip to Goa", "text": "Day 1: beach."}], "document") == ["title: Trip to Goa | text: Day 1: beach."]
    assert server.prefixed([{"text": "no title here"}], "document") == ["title: none | text: no title here"]
    with pytest.raises(ValueError):
        server.prefixed([{"title": "x"}], "document")  # no text


def test_a_picture_is_its_words_and_its_image_in_one_input(tmp_path, monkeypatch):
    from PIL import Image
    pic = tmp_path / "a.jpeg"
    Image.new("RGB", (3000, 2000), "blue").save(pic)
    seen = []

    def fake_encode(inputs):
        seen.append(inputs)
        return [[0.0, 2.0] for _ in inputs]
    monkeypatch.setattr(server, "_encode", fake_encode)
    c = TestClient(server.app)
    body = {"kind": "picture", "input": [{"text": "Asha · Beach, Sea · Goa · 16 May 2024", "image": str(pic)}, {"text": "Dog · 1 Mar 2022"}]}
    r = c.post("/v1/embeddings", json=body)
    assert r.status_code == 200 and [x["embedding"] for x in r.json()["data"]] == [[0.0, 1.0], [0.0, 1.0]]
    [batch] = seen
    assert batch[0]["text"] == "title: none | text: Asha · Beach, Sea · Goa · 16 May 2024 <|image|>"
    assert max(batch[0]["image"][0].size) == 1024 and batch[0]["image"][0].mode == "RGB"  # shrunk, never the 3000 px original
    assert batch[1] == "title: none | text: Dog · 1 Mar 2022"  # no copy on this Mac: its words alone, as a document
    r = c.post("/v1/embeddings", json={"kind": "picture", "input": [{"text": "x", "image": str(tmp_path / "missing.jpeg")}]})
    assert r.status_code == 400 and "missing.jpeg" in r.json()["detail"]
    r = c.post("/v1/embeddings", json={"kind": "picture", "input": ["just a string"]})
    assert r.status_code == 400
    too_many = {"kind": "picture", "input": [{"text": "x", "image": str(pic)}] * (server.PICTURES_MOST + 1)}
    assert c.post("/v1/embeddings", json=too_many).status_code == 400


def test_health_says_it_reads_pictures():
    assert TestClient(server.app).get("/health").json()["pictures"] is True


def test_an_unreadable_picture_file_falls_back_to_its_words(tmp_path, monkeypatch):
    """A file that exists but isn't an image (a movie, a broken download) costs that one picture its pixels, never the
    whole batch: the service encodes its words alone and carries on."""
    movie = tmp_path / "clip.mov"
    movie.write_bytes(b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 40)
    seen = []
    monkeypatch.setattr(server, "_encode", lambda inputs: (seen.append(inputs) or [[1.0, 0.0] for _ in inputs]))
    c = TestClient(server.app)
    r = c.post("/v1/embeddings", json={"kind": "picture", "input": [{"text": "Sea, Boat · video", "image": str(movie)}]})
    assert r.status_code == 200
    assert seen == [["title: none | text: Sea, Boat · video"]]


# ── the first run (2026-10-14): the model downloads in the background, and the service says so ──
def test_health_says_whether_the_model_is_cached_and_downloading(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(server, "_downloading", False)
    monkeypatch.setattr(server, "_download_error", "")
    c = TestClient(server.app)
    d = c.get("/health").json()
    assert d["cached"] is False and d["downloading"] is False
    snap = tmp_path / "models--google--embeddinggemma-2" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    assert c.get("/health").json()["cached"] is True


def test_embedding_while_the_model_downloads_is_a_plain_503(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(server, "_downloading", True)
    c = TestClient(server.app)
    r = c.post("/v1/embeddings", json={"input": ["a"], "kind": "query"})
    assert r.status_code == 503 and "downloading" in r.json()["detail"]
