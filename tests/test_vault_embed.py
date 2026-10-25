"""Meaning search: the embedding providers' requests, the one-sentence check, vectors that follow their chunks, and
keyword and meaning results merged by reciprocal rank fusion."""
import hashlib
import json
import math
import shutil
import time
from pathlib import Path

import httpx
import pytest

from odie.vault import embed
from odie.vault.embed import EmbedError, check, make_embedder
from odie.vault.index import VaultIndex

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"
SAME = {"vacation": "travel", "holiday": "travel", "trip": "travel", "goa": "travel", "pulses": "dal", "lentils": "dal"}


class FakeEmbedder:
    """Hashed bags of words, with a few synonyms folded together, so texts that share meaning are near."""
    sees_pictures = False

    def __init__(self, name="fake:words", dims=64, fail=False):
        self.name, self.dims, self.fail, self.calls = name, dims, fail, 0
        self.kinds = []  # what the index said each batch was: "document" or "query"
        self.documents = []  # the documents as handed over ({"title", "text"} for a note's passage)

    async def embed(self, texts, kind="document"):
        self.kinds.append(kind)
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedding server down")
        out = []
        for t in texts:
            if isinstance(t, dict):
                self.documents.append(t)
                t = f"{t.get('title') or ''} > {t['text']}"
            v = [0.0] * self.dims
            for w in t.lower().replace(">", " ").split():
                w = SAME.get(w.strip(".,:;!?()[]#"), w.strip(".,:;!?()[]#"))
                if w:
                    v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dims] += 1.0
            out.append(v)
        return out


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    shutil.copytree(SAMPLE, v)
    return v


@pytest.fixture
def index(vault, tmp_path):
    ix = VaultIndex(tmp_path / "vault-index.db", vault)
    ix.scan()
    return ix


async def test_each_provider_sends_its_own_request_shape(isolated_settings, monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((str(request.url), request.headers.get("authorization"), body))
        n = len(body["input"])
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0]] * n})
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [float(i), 1.0]} for i in reversed(range(n))]})
    t = httpx.MockTransport(handler)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-only")
    assert await make_embedder("openai", "text-embedding-3-small", transport=t).embed(["a", "b"]) == [[0.0, 1.0], [1.0, 1.0]]
    await make_embedder("lmstudio", "nomic-embed", transport=t).embed(["a"])
    assert await make_embedder("ollama", "nomic-embed-text", transport=t).embed(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]
    (u1, a1, b1), (u2, _, b2), (u3, _, b3) = seen
    assert u1 == "https://api.openai.com/v1/embeddings" and a1 == "Bearer sk-test-only" and b1 == {"model": "text-embedding-3-small", "input": ["a", "b"]}
    assert u2.endswith("/v1/embeddings") and b2["model"] == "nomic-embed"
    assert u3 == "http://localhost:11434/api/embed" and b3 == {"model": "nomic-embed-text", "input": ["a", "b"]}
    assert make_embedder("ollama", "nomic-embed-text").name == "ollama:nomic-embed-text"


async def test_openai_without_a_key_says_so(isolated_settings, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EmbedError, match="OpenAI key"):
        make_embedder("openai", "text-embedding-3-small")


async def test_check_reports_a_plain_reason(isolated_settings):
    def refused(request):
        return httpx.Response(401, json={"error": "bad key"})

    def down(request):
        raise httpx.ConnectError("refused")

    def empty(request):
        return httpx.Response(200, json={"embeddings": [[]]})
    with pytest.raises(EmbedError, match="refused"):
        await check(make_embedder("ollama", "m", transport=httpx.MockTransport(refused)))
    with pytest.raises(EmbedError, match="reach"):
        await check(make_embedder("ollama", "m", transport=httpx.MockTransport(down)))
    with pytest.raises(EmbedError, match="empty"):
        await check(make_embedder("ollama", "m", transport=httpx.MockTransport(empty)))

    def ok(request):
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})
    assert await check(make_embedder("ollama", "m", transport=httpx.MockTransport(ok))) == 3


async def test_meaning_search_finds_what_keywords_miss(index):
    e = FakeEmbedder()
    assert await index.embed_pending(e) == index.status()["chunks"]
    assert index.keyword("vacation") == []
    hits = await index.search("vacation", embedder=e)
    assert hits and hits[0].path == "1-Projects/Trip to Goa.md"
    stored = index.status()
    assert stored["model"] == "fake:words" and stored["vectors"] == stored["chunks"]


async def test_fusion_keeps_keyword_hits_first_when_meaning_agrees(index):
    e = FakeEmbedder()
    await index.embed_pending(e)
    hits = await index.search("pressure cook the lentils", embedder=e)
    assert hits[0].path == "Recipes/Dal.md" and hits[0].score > 0
    assert len({(h.path, h.heading) for h in hits}) == len(hits)  # one entry per chunk, never twice


async def test_vectors_follow_chunks(index, vault):
    e = FakeEmbedder()
    await index.embed_pending(e)
    dal = vault / "Recipes" / "Dal.md"
    dal.write_text("# Dal\nNow with tamarind.\n")
    future = time.time() + 5
    import os
    os.utime(dal, (future, future))
    (vault / "Home.md").unlink()
    index.scan()
    st = index.status()
    assert (st["chunks"], st["vectors"]) == (2, 1)  # Home's vector went with it; Dal's old one with its old text
    assert await index.embed_pending(e) == 1  # only the changed note's chunk
    st = index.status()
    assert st["vectors"] == st["chunks"] == 2


async def test_changing_the_model_rebuilds_vectors(index):
    await index.embed_pending(FakeEmbedder("fake:a", dims=64))
    other = FakeEmbedder("fake:b", dims=32)
    assert index.keyword("lentils")  # keyword search keeps working throughout
    assert await index.embed_pending(other) == index.status()["chunks"]
    assert index.status()["model"] == "fake:b"
    hits = await index.search("lentils", embedder=other)
    assert hits[0].path == "Recipes/Dal.md"


async def test_meaning_search_falls_back_to_keywords(index, vault):
    good = FakeEmbedder()
    await index.embed_pending(good)
    broken = FakeEmbedder(fail=True)
    hits = await index.search("lentils", embedder=broken)
    assert [h.path for h in hits] == [h.path for h in index.keyword("lentils")]
    dal = vault / "Recipes" / "Dal.md"
    dal.write_text("# Dal\nNow with lentils and tamarind.\n")
    import os
    os.utime(dal, (time.time() + 5, time.time() + 5))
    index.scan()
    assert await index.embed_pending(broken) == 0 and "down" in (index.status()["embed_error"] or "")
    assert index.keyword("tamarind")  # keyword search still answers while meaning is behind
    await index.embed_pending(good)
    assert index.status()["embed_error"] is None  # cleared once it works again


async def test_related_by_meaning_and_by_links(index):
    by_links = await index.related("Home")
    assert {h.path for h in by_links} == {"1-Projects/Trip to Goa.md", "Recipes/Dal.md"}
    await index.embed_pending(FakeEmbedder())
    near = await index.related("Dal")
    assert near and all(h.path != "Recipes/Dal.md" for h in near)
    assert await index.related("Nope") == []


def test_vectors_are_stored_normalised(index):
    import asyncio
    import sqlite3
    from array import array
    asyncio.run(index.embed_pending(FakeEmbedder()))
    blob = sqlite3.connect(index.db_path).execute("select vec from vectors limit 1").fetchone()[0]
    v = array("f")
    v.frombytes(blob)
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-5)


async def test_the_same_index_sees_a_model_switch_and_a_rewritten_vector(index, vault):
    """One VaultIndex lives for the whole process: its vector cache must notice every rewrite."""
    a = FakeEmbedder("fake:a", dims=64)
    await index.embed_pending(a)
    assert await index.search("vacation", embedder=a)  # fills the cache
    b = FakeEmbedder("fake:b", dims=32)
    await index.embed_pending(b)
    hits = await index.search("vacation", embedder=b)
    assert hits and hits[0].path == "1-Projects/Trip to Goa.md"  # meaning search with the new model, not silently off
    before = dict(zip(*index._vectors()))
    dal = vault / "Recipes" / "Dal.md"  # the last note: its chunk's id is reused when it is rewritten
    dal.write_text("# Dal\nNow with tamarind and jaggery.\n")
    import os
    os.utime(dal, (time.time() + 5, time.time() + 5))
    index.scan()
    await index.embed_pending(b)
    after = dict(zip(*index._vectors()))
    changed = [cid for cid in after if cid in before and list(after[cid]) != list(before[cid])]
    assert changed, "the cache served the old vector"


def test_vectors_are_kept_compact(index):
    import asyncio
    from array import array
    asyncio.run(index.embed_pending(FakeEmbedder()))
    ids, vecs = index._vectors()
    assert vecs and all(isinstance(v, array) for v in vecs)


async def test_gemma_sends_the_kind_to_odies_own_service(isolated_settings, monkeypatch):
    """EmbeddingGemma 2 runs in Odie's own service (embed_server): the request carries `kind`, so the service adds the
    right prefix; the service is started first when it isn't up."""
    import httpx

    from odie import embed_worker
    from odie.vault import embed
    seen = []

    def handler(req):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.6, 0.8]}], "model": "google/embeddinggemma-2"})

    class Up:
        url = "http://127.0.0.1:8772"
        problem = ""

        async def ensure(self, timeout=30):
            return True
    monkeypatch.setattr(embed_worker, "current", Up())
    e = embed.make_embedder("gemma", "google/embeddinggemma-2", transport=httpx.MockTransport(handler))
    assert e.name == "gemma:google/embeddinggemma-2"
    assert await e.embed(["what is a vault?"], kind="query") == [[0.6, 0.8]]
    assert seen[0][0] == "http://127.0.0.1:8772/v1/embeddings" and seen[0][1] == {"model": "google/embeddinggemma-2", "input": ["what is a vault?"], "kind": "query"}
    await e.embed(["a note"])
    assert seen[1][1]["kind"] == "document"


async def test_gemma_says_why_when_the_service_cant_start(isolated_settings, monkeypatch):
    from odie import embed_worker
    from odie.vault import embed

    class Down:
        url = "http://127.0.0.1:8772"
        problem = "local embeddings isn't set up: run `uv sync` in embed_server"

        async def ensure(self, timeout=30):
            return False
    monkeypatch.setattr(embed_worker, "current", Down())
    with pytest.raises(embed.EmbedError, match="uv sync"):
        await embed.make_embedder("gemma", "google/embeddinggemma-2").embed(["x"])


async def test_other_providers_never_send_the_kind(isolated_settings, monkeypatch):
    import httpx

    from odie.vault import embed
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
    e = embed.make_embedder("lmstudio", "nomic", transport=httpx.MockTransport(handler))
    await e.embed(["x"], kind="query")
    assert "kind" not in seen[0]


async def test_the_question_is_embedded_as_a_query_and_notes_as_documents(index):
    """Gemma's prefixes differ for the two sides, so the index says which it is sending."""
    e = FakeEmbedder()
    await index.embed_pending(e)
    await index.search("a question", embedder=e)
    assert e.kinds and set(e.kinds[:-1]) == {"document"} and e.kinds[-1] == "query"


async def test_odies_own_service_says_when_its_model_is_still_downloading(isolated_settings, monkeypatch):
    """The first run on a Mac: the model (1.5 GB) is fetched in the background; until then embedding is refused
    with a plain reason the worker records and retries, and the setup check passes without a sentence."""
    from odie import embed_worker

    class Up:
        url = "http://127.0.0.1:1"
        problem = ""

        async def ensure(self):
            return True
    monkeypatch.setattr(embed_worker, "current", Up())
    state = {"cached": False}

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "model": "google/embeddinggemma-2", "dims": 768, "loaded": False,
                                             "cached": state["cached"], "downloading": not state["cached"], "pictures": True})
        if not state["cached"]:
            return httpx.Response(503, json={"detail": "the model is still downloading"})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    gemma = make_embedder("gemma", "google/embeddinggemma-2", transport=httpx.MockTransport(handler))
    assert await gemma.preparing() is True
    with pytest.raises(EmbedError, match="still downloading"):
        await gemma.embed(["a"])
    with pytest.raises(EmbedError, match="still downloading"):
        await gemma.embed_pictures([("a", None)])
    assert await check(gemma) == 0  # not measured: the model isn't here yet, and that's not a failure
    state["cached"] = True
    assert await gemma.preparing() is False
    assert await gemma.embed(["a"]) == [[1.0, 0.0]] and await check(gemma) == 2


async def test_an_embedder_can_live_on_another_computer(isolated_settings):
    """A server somewhere else: Ollama at its root address, or any OpenAI-style server (LM Studio, llama.cpp) at its
    /v1 base. Without an address the built-in ones stay on this computer."""
    import json
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, str(request.url), json.loads(request.content) if request.content else None))
        if request.url.path.endswith("/api/embed"):
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
        if request.url.path.endswith("/api/show"):
            return httpx.Response(200, json={"capabilities": ["embedding", "vision"]})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0, 1.0]}]})
    t = httpx.MockTransport(handler)
    far = make_embedder("ollama", "embeddinggemma-2", transport=t, pictures=True, url="http://studio.local:11434/")
    assert await far.embed(["a"]) == [[1.0, 0.0]] and seen[-1][1] == "http://studio.local:11434/api/embed"
    assert await embed.ollama_sees_pictures("embeddinggemma-2", t, url="http://studio.local:11434") is True
    assert seen[-1][1] == "http://studio.local:11434/api/show"
    server = make_embedder("server", "text-embedding-x", transport=t, url="http://192.168.1.20:1234/v1")
    assert await server.embed(["a"]) == [[0.0, 1.0]] and seen[-1][1] == "http://192.168.1.20:1234/v1/embeddings"
    assert server.sees_pictures is False and server.name == "server:text-embedding-x"
    home = make_embedder("ollama", "nomic-embed-text", transport=t)
    await home.embed(["a"])
    assert seen[-1][1] == "http://localhost:11434/api/embed"
    with pytest.raises(EmbedError, match="address"):
        make_embedder("server", "text-embedding-x", transport=t)


async def test_the_models_a_server_offers(isolated_settings):
    """What an address has to pick from: Ollama's /api/tags, an OpenAI-style server's /v1/models; the embedding ones
    (their name says embed). Unreachable: no models and a plain reason."""
    def handler(request: httpx.Request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "embeddinggemma-2:740m"}, {"name": "gemma4:12b"}]})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "text-embedding-embeddinggemma-2"}, {"id": "gemma-4-12b"}]})
        return httpx.Response(404)
    t = httpx.MockTransport(handler)
    assert await embed.server_models("ollama", "http://studio.local:11434", t) == (["embeddinggemma-2:740m"], "")
    assert await embed.server_models("server", "http://192.168.1.20:1234/v1", t) == (["text-embedding-embeddinggemma-2"], "")
    models, why = await embed.server_models("ollama", "http://nowhere.local:11434", httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no route"))))
    assert models == [] and "couldn't reach" in why
