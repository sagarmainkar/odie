"""Odie's own embedding service: EmbeddingGemma 2 (google/embeddinggemma-2) on this Mac, so notes and pictures are
read by meaning without anything leaving the computer. Listens on 127.0.0.1 only; Odie starts it by itself
(odie/embed_worker.py) on ODIE_EMBED_PORT (8772) and it exits when that Odie does.

The request is OpenAI's embeddings shape plus `kind`: "query" for a question, "document" for a note's chunk (a string,
or {"title", "text"} so the note's real title goes in), "picture" for a photo or video ({"text": its words, "image":
a file on this Mac}, the image left out when there's no copy here). The service adds Gemma's own prefixes (its model
card: `task: search result | query: …`, `title: {title} | text: …`, and nothing on an image, which follows the words as
`<|image|>` in one input, so a picture is one vector of its words and its pixels together). Odie never has to know
them. Vectors are 768 wide, unit length. The first run downloads the model from Hugging Face (about
1.5 GB, into ~/.cache/huggingface); no account is needed, though HF_TOKEN is used if set. After a quiet spell
(ODIE_EMBED_IDLE_MINUTES, 15 by default) the model is unloaded and its memory given back; the next request loads it
again. By hand, for trying it alone:

    uv run uvicorn server:app --host 127.0.0.1 --port 8772
"""
from __future__ import annotations

import asyncio
import gc
import math
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MODEL = "google/embeddinggemma-2"
DIMS = 768
# Measured on an Apple silicon Mac with 32 GB (14 Oct 2026): the loaded model holds 1.4 GB of GPU memory (bf16, all three encoders);
# a batch of 16 chunks of 1,024 tokens peaks at 4.7 GB and takes 2.2 s; 8 images of 1024x768 peak at 3.7 GB in 2.1 s;
# the cache is given back after each batch, to about 1.7 GB. Batches of 32 chunks of 2,000 tokens, before these caps,
# ran the GPU out of memory next to a loaded 26B chat model and froze the Mac.
MAX_TOKENS = 1024  # a chunk is read up to here: enough for retrieval, and bounds the GPU memory a batch takes
BATCH = 8          # chunks encoded at once: about 3 GB at the peak, next to whatever chat model shares the GPU
PICTURES_MOST = 16  # pictures per request (two batches): the caller sends more in further requests
PICTURE_SIDE = 1024  # a picture is shrunk to this on its longest side before the model sees it (measured: 4 GB peak)
# Gemma's prefixes for the two sides of a search (the model card's "SearchQuery" and "Document" prompts).
PREFIX = {"query": "task: search result | query: ", "document": "title: none | text: "}
# After this many minutes without a request the model is unloaded (its GPU memory given back); the next request loads
# it again (about 7 s). ODIE_EMBED_IDLE_MINUTES in ~/.odie/.env sets it; 0 keeps the model loaded.
IDLE_MINUTES = float(os.environ.get("ODIE_EMBED_IDLE_MINUTES", "15"))
_model = None
_last_used = 0.0
_lock = threading.Lock()  # one load, and one batch at a time on the GPU
_downloading = False      # the first run: the model's files are being fetched from Hugging Face (about 1.5 GB)
_download_error = ""

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """At start: the janitor that unloads an idle model, and on a first run the model download in the background."""
    janitor = asyncio.create_task(_janitor())
    if not cached() and not _downloading:
        threading.Thread(target=_prefetch, daemon=True).start()
    yield
    janitor.cancel()


app = FastAPI(title="odie-embed", lifespan=_lifespan)


class EmbedIn(BaseModel):
    input: str | list  # strings; {"title", "text"} documents; {"text", "image"} pictures
    kind: str = "document"
    model: str | None = None  # accepted for OpenAI's shape; there is one model here


def prefixed(items: list, kind: str) -> list[str]:
    """Each text with Gemma's prefix for its side of the search; a document may carry its real title.
      (["what causes northern lights?"], "query")           -> ["task: search result | query: what causes northern lights?"]
      (["Charged particles from the sun."], "document")      -> ["title: none | text: Charged particles from the sun."]
      ([{"title": "Trip", "text": "Day 1"}], "document")     -> ["title: Trip | text: Day 1"]
      kind "picture" -> ValueError (pictures go through picture_inputs)"""
    if kind not in PREFIX:
        raise ValueError(f"kind is query or document, not {kind!r}")
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(PREFIX[kind] + item if kind == "query" else document_text(None, item))
        elif isinstance(item, dict) and isinstance(item.get("text"), str) and kind == "document":
            out.append(document_text(item.get("title"), item["text"]))
        else:
            raise ValueError("a document is a string or {title, text}; a query is a string")
    return out


def document_text(title, text: str) -> str:
    """The model card's document form: `title: {title} | text: {content}`, `none` for no title."""
    clean = " ".join(str(title).split()) if title else ""
    return f"title: {clean or 'none'} | text: {text}"


def picture_inputs(items: list) -> list:
    """What the model gets for pictures: each item's words as a document, with its image after them when the item
    names one; a bare text when it doesn't (no copy of the picture on this Mac). Images are opened and shrunk here.
      [{"text": "Asha · Beach", "image": "/lib/a.jpeg"}] -> [{"text": "title: none | text: Asha · Beach <|image|>", "image": [<1024 px RGB>]}]
      [{"text": "Dog · 1 Mar 2022"}]                      -> ["title: none | text: Dog · 1 Mar 2022"]
      a file that exists but isn't an image (a movie)       -> that item's words alone
      a missing file, a bare string, more than PICTURES_MOST -> ValueError"""
    if len(items) > PICTURES_MOST:
        raise ValueError(f"at most {PICTURES_MOST} pictures per request")
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("a picture is {text, image?}")
        words = document_text(None, item["text"])
        path = item.get("image")
        if not path:
            out.append(words)
            continue
        if not isinstance(path, str) or not os.path.isfile(path):
            raise ValueError(f"no such picture file: {path}")
        try:
            image = shrunk(path)
        except Exception as e:  # noqa: BLE001  (a movie, a broken file: this picture's words alone, the batch goes on)
            print(f"picture unreadable, its words alone: {path}: {type(e).__name__}", flush=True)
            out.append(words)
            continue
        out.append({"text": words + " <|image|>", "image": [image]})
    return out


def shrunk(path: str):
    """The picture as RGB with its longest side at most PICTURE_SIDE (a 48-megapixel original costs the same as a small one)."""
    from PIL import Image
    im = Image.open(path)
    im = im.convert("RGB")
    im.thumbnail((PICTURE_SIDE, PICTURE_SIDE))
    return im


def cached() -> bool:
    """Whether the model's files are in the Hugging Face cache (HF_HUB_CACHE, else ~/.cache/huggingface/hub): a
    snapshot folder with its config.json. False on the first run, until the download finishes."""
    root = os.environ.get("HF_HUB_CACHE") or os.path.join(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface")), "hub")
    snapshots = os.path.join(root, "models--" + MODEL.replace("/", "--"), "snapshots")
    try:
        return any(os.path.isfile(os.path.join(snapshots, d, "config.json")) for d in os.listdir(snapshots))
    except OSError:
        return False


def _prefetch() -> None:
    """Fetch the model's files now (a thread started at launch when they aren't cached), so the first search doesn't
    wait on a download and the index worker's next pass finds them here."""
    global _downloading, _download_error
    _downloading, _download_error = True, ""
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL)
    except Exception as e:  # noqa: BLE001
        _download_error = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        _downloading = False


def should_unload(loaded: bool, last_used: float, now: float, idle_minutes: float) -> bool:
    """Whether the quiet spell is over the limit: loaded, a limit set, and nothing asked for idle_minutes.
      (True, last used 20 min ago, 15)  -> True;  (True, 5 min ago, 15) -> False;  (True, 20 min ago, 0) -> False (never);
      (False, …) -> False (nothing to unload)"""
    if not loaded or idle_minutes <= 0:
        return False
    return now - last_used >= idle_minutes * 60


def _load():
    global _model, _last_used
    with _lock:
        if _model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            _model = SentenceTransformer(MODEL, model_kwargs={"torch_dtype": torch.bfloat16}).to(device)
            _model.max_seq_length = MAX_TOKENS
        _last_used = time.time()
    return _model


def _unload() -> None:
    global _model
    with _lock:
        _model = None
        gc.collect()
        try:
            import torch
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except ImportError:
            pass


async def _janitor() -> None:
    while True:
        await asyncio.sleep(60)
        if should_unload(_model is not None, _last_used, time.time(), IDLE_MINUTES) and not _lock.locked():
            _unload()


def _encode(inputs: list) -> list[list[float]]:
    """The model's vectors for already-prefixed inputs: strings, or {"text", "image"} for a picture with its words
    (tests replace this; the suite never loads the model). Strings and pictures are encoded in separate calls."""
    model = _load()
    with _lock:
        import torch
        out: list = [None] * len(inputs)
        try:
            with torch.no_grad():
                for group in (str, dict):
                    where = [i for i, x in enumerate(inputs) if isinstance(x, group)]
                    if not where:
                        continue
                    vecs = model.encode([inputs[i] for i in where], batch_size=BATCH, normalize_embeddings=True, convert_to_numpy=True)
                    for i, v in zip(where, vecs.tolist()):
                        out[i] = v
        finally:
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()  # give the batch's working memory back at once
        return out


def _unit(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL, "dims": DIMS, "loaded": _model is not None, "idle_minutes": IDLE_MINUTES, "pictures": True,
            "cached": cached(), "downloading": _downloading, "download_error": _download_error}


@app.post("/v1/embeddings")
async def embeddings(req: EmbedIn):
    items = [req.input] if isinstance(req.input, str) else list(req.input)
    if not items:
        raise HTTPException(400, "input: a string or a list")
    if _downloading or not cached():
        raise HTTPException(503, "the model is still downloading (about 1.5 GB); try again in a few minutes"
                            + (f" (last attempt: {_download_error})" if _download_error else ""))
    try:
        prompts = await asyncio.to_thread(picture_inputs, items) if req.kind == "picture" else prefixed(items, req.kind)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(400, f"couldn't open a picture: {e}")
    try:
        vectors = await asyncio.to_thread(_encode, prompts)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:200]}")
    data = [{"object": "embedding", "index": i, "embedding": _unit([float(x) for x in v])} for i, v in enumerate(vectors)]
    tokens = sum(len((p if isinstance(p, str) else p["text"]).split()) for p in prompts)  # a rough count, as OpenAI's shape has one
    return {"object": "list", "data": data, "model": MODEL, "usage": {"prompt_tokens": tokens, "total_tokens": tokens}}


def _watch_parent() -> None:
    """Started by Odie: exit when that Odie is gone, however it went (the pipe it holds closes)."""
    fd = os.environ.get("ODIE_PARENT_FD")
    if fd:
        def wait():
            try:
                os.read(int(fd), 1)
            finally:
                os._exit(0)
        threading.Thread(target=wait, daemon=True).start()


_watch_parent()
