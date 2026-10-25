"""Embedding providers for the index: OpenAI, LM Studio, Ollama and Odie's own service (EmbeddingGemma 2 on this Mac,
odie.embed_worker), each over its own HTTP API, and a check that embeds one sentence so a wrong key, a model that
isn't loaded or a server that's down is caught when it's chosen. A request says which side of a search it is (`kind`:
document or query); only Odie's own service is told, since it adds Gemma's prefixes, and OpenAI-style APIs refuse
fields they don't know. Only Odie's own service reads pictures (embed_pictures): the others get a plain refusal."""
from __future__ import annotations

from typing import Protocol

import httpx

from odie import config
from odie.secrets import load_secret

OLLAMA_URL = "http://localhost:11434"
BATCH = 32
PICTURE_BATCH = 8  # pictures per request to Odie's own service: about 4 GB of GPU memory at the peak (measured 14 Oct 2026)
CHECK_SENTENCE = "Odie checks that it can read your notes by meaning."
NO_PICTURES = "pictures by meaning need EmbeddingGemma 2: Odie's own embedding service, or embeddinggemma-2 on Ollama"
PICTURE_SIDE = 1024  # a picture goes to Ollama no wider or taller than this: the model reads a small image anyway
PREPARING = "the embedding model is still downloading (about 1.5 GB); Odie tries again in a few minutes"


class EmbedError(Exception):
    """A plain reason, said to the user as it is."""


class Embedder(Protocol):
    name: str
    sees_pictures: bool  # can it make a vector from a picture's words and pixels together? (Odie's own service only)

    async def embed(self, texts: list, kind: str = "document") -> list[list[float]]: ...

    async def embed_pictures(self, items: list[tuple[str, str | None]]) -> list[list[float]]: ...


class HttpEmbedder:
    sees_pictures = False

    def __init__(self, provider: str, model: str, url: str, headers: dict[str, str], transport=None, says_kind: bool = False) -> None:
        self.provider, self.model, self.url, self.headers, self.transport = provider, model, url, headers, transport
        self.says_kind = says_kind  # the request carries `kind` (Odie's own service); the others would refuse the field
        self.name = f"{provider}:{model}"

    async def _batch(self, c: httpx.AsyncClient, texts: list, kind: str) -> list[list[float]]:
        body: dict = {"model": self.model, "input": texts if self.says_kind else [flat(t) for t in texts]}
        if self.says_kind:
            body["kind"] = kind
        return await self._send(c, body)

    async def _send(self, c: httpx.AsyncClient, body: dict) -> list[list[float]]:
        """One request to the provider, its vectors back; a refusal or an outage as a plain EmbedError."""
        try:
            r = await c.post(self.url, json=body, headers=self.headers)
        except httpx.HTTPError as e:
            raise EmbedError(f"couldn't reach {self.provider} at {self.url} ({type(e).__name__})") from e
        if r.status_code in (401, 403):
            raise EmbedError(f"{self.provider} refused the key ({r.status_code})")
        if r.status_code == 404:
            raise EmbedError(f"{self.provider} doesn't have the model {self.model} (or its embeddings endpoint)")
        if r.status_code == 503 and self.says_kind:
            raise EmbedError(PREPARING)
        if r.status_code >= 400:
            raise EmbedError(f"{self.provider} said {r.status_code}: {r.text[:160]}")
        d = r.json()
        if "embeddings" in d:  # Ollama
            return [list(map(float, v)) for v in d["embeddings"]]
        return [list(map(float, x["embedding"])) for x in sorted(d.get("data") or [], key=lambda x: x.get("index", 0))]

    async def embed(self, texts: list, kind: str = "document") -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=120, transport=self.transport) as c:
            for i in range(0, len(texts), BATCH):
                out += await self._batch(c, texts[i:i + BATCH], kind)
        return out

    async def embed_pictures(self, items: list[tuple[str, str | None]]) -> list[list[float]]:
        raise EmbedError(NO_PICTURES)


class OllamaEmbedder(HttpEmbedder):
    """Ollama's /api/embed. A model that sees pictures there (EmbeddingGemma 2, "vision" among its capabilities;
    ollama_sees_pictures) takes each picture as {"text": its words, "image": base64 JPEG} and gives one vector for
    both (checked live 25 Oct 2026: two photos sit at 0.69, the words barely move a photo's vector)."""

    def __init__(self, model: str, transport=None, pictures: bool = False) -> None:
        super().__init__("ollama", model, OLLAMA_URL + "/api/embed", {}, transport)
        self.sees_pictures = pictures

    async def embed_pictures(self, items: list[tuple[str, str | None]]) -> list[list[float]]:
        """items: (the picture's words, the path of its copy on this Mac or None). A copy that can't be read as an
        image goes by its words alone. Sent PICTURE_BATCH at a time."""
        if not self.sees_pictures:
            raise EmbedError(NO_PICTURES)
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=300, transport=self.transport) as c:
            for i in range(0, len(items), PICTURE_BATCH):
                body = []
                for text, path in items[i:i + PICTURE_BATCH]:
                    image = picture_payload(path) if path else None
                    body.append({"text": text, "image": image} if image else {"text": text})
                out += await self._send(c, {"model": self.model, "input": body})
        return out


def picture_payload(path: str) -> str | None:
    """A picture's copy as the model should get it: a JPEG no wider or taller than PICTURE_SIDE, base64. None when the
    file can't be read as an image (a movie, a broken copy), so the picture goes by its words.
      a 4000×3000 JPEG -> base64 of a 1024×768 JPEG;  "clip.mov" or junk bytes -> None"""
    import base64
    import io
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((PICTURE_SIDE, PICTURE_SIDE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
    except Exception:  # noqa: BLE001 (any unreadable file: words only)
        return None
    return base64.b64encode(buf.getvalue()).decode()


async def ollama_sees_pictures(model: str, transport=None) -> bool:
    """Whether this Ollama model takes pictures: "vision" among the capabilities `ollama show` lists. False when Ollama
    can't be asked or doesn't know the model.
      embeddinggemma-2:740m (embedding, vision, audio) -> True;  nomic-embed-text (embedding) -> False"""
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as c:
            r = await c.post(OLLAMA_URL + "/api/show", json={"model": model})
            caps = r.json().get("capabilities") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
    return "vision" in caps


def flat(item) -> str:
    """A document for an API that takes plain strings: {"title": "Trip", "text": "Day 1"} -> "Trip\nDay 1"; a string as it is."""
    if isinstance(item, dict):
        title = item.get("title") or ""
        return f"{title}\n{item['text']}" if title else item["text"]
    return item


class ServiceEmbedder(HttpEmbedder):
    """Odie's own service: started first when it isn't up (odie.embed_worker), with its reason when it can't be. It
    reads pictures too: each one's words and its image file (on this Mac) become one vector."""
    sees_pictures = True

    async def _up(self) -> None:
        from odie import embed_worker
        worker = embed_worker.current
        if worker is None:
            raise EmbedError("Odie's embedding service isn't running (is ODIE_EMBED off?)")
        if not await worker.ensure():
            raise EmbedError(worker.problem or "Odie's embedding service didn't start")

    async def preparing(self) -> bool:
        """Whether the service is still fetching its model (the first run on a Mac): /health says cached or not.
        A service that can't be asked counts as not preparing; the embedding call then says what's wrong."""
        await self._up()
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as c:
                r = await c.get(self.url.rsplit("/v1/", 1)[0] + "/health")
                d = r.json()
        except Exception:  # noqa: BLE001
            return False
        return bool(d.get("downloading")) or d.get("cached") is False

    async def embed(self, texts: list, kind: str = "document") -> list[list[float]]:
        await self._up()
        if await self.preparing():
            raise EmbedError(PREPARING)
        return await super().embed(texts, kind)

    async def embed_pictures(self, items: list[tuple[str, str | None]]) -> list[list[float]]:
        """items: (the picture's words, the path of its copy on this Mac or None). Sent PICTURE_BATCH at a time."""
        await self._up()
        if await self.preparing():
            raise EmbedError(PREPARING)
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=300, transport=self.transport) as c:
            for i in range(0, len(items), PICTURE_BATCH):
                body = []
                for text, image in items[i:i + PICTURE_BATCH]:
                    body.append({"text": text, "image": image} if image else {"text": text})
                out += await self._batch(c, body, "picture")
        return out


def make_embedder(provider: str, model: str, store=None, transport=None, pictures: bool = False) -> HttpEmbedder:
    """provider: openai | lmstudio | ollama | gemma (Odie's own service). pictures: the Ollama model sees pictures
    (the vault setting remembers it, from ollama_sees_pictures when the model was chosen)."""
    if provider == "openai":
        key = load_secret("OPENAI_API_KEY")
        if not key:
            raise EmbedError("Add an OpenAI key in Settings → Providers first.")
        return HttpEmbedder("openai", model, "https://api.openai.com/v1/embeddings", {"Authorization": f"Bearer {key}"}, transport)
    if provider == "lmstudio":
        s = config.settings
        return HttpEmbedder("lmstudio", model, s.lm_studio_base_url.rstrip("/") + "/embeddings",
                            {"Authorization": f"Bearer {s.lm_studio_api_key}"}, transport)
    if provider == "ollama":
        return OllamaEmbedder(model, transport, pictures)
    if provider == "gemma":
        from odie import embed_worker
        base = embed_worker.current.url if embed_worker.current is not None else f"http://127.0.0.1:{embed_worker.embed_port()}"
        return ServiceEmbedder("gemma", model, base + "/v1/embeddings", {}, transport, says_kind=True)
    raise EmbedError(f"unknown embedding provider {provider!r} (openai, lmstudio, ollama or gemma)")


async def check(embedder: Embedder) -> int:
    """Embed one sentence; the vector size, or EmbedError with the reason. 0 when the embedder is Odie's own service
    still fetching its model: not a failure, the sentence just can't be tried yet."""
    try:
        preparing = getattr(embedder, "preparing", None)
        if preparing is not None and await preparing():
            return 0
        vecs = await embedder.embed([CHECK_SENTENCE])
    except EmbedError:
        raise
    except Exception as e:  # noqa: BLE001
        raise EmbedError(f"{type(e).__name__}: {e}") from e
    if not vecs or not vecs[0]:
        raise EmbedError("the model returned an empty vector")
    return len(vecs[0])
