"""Odie's own embedding service worker: embed_server/ (EmbeddingGemma 2 on this Mac), started by Odie as a child process
on its own port (ODIE_EMBED_PORT, 8772) the way the voice worker is (odie/voice_worker.py: it dies with its Odie, is
never someone else's, and is never in the way). Started at launch only when the vault's embeddings are set to Odie's
own service, and on demand when that is chosen in Settings."""
from __future__ import annotations

import os
from pathlib import Path

from odie.secrets import load_secret
from odie.voice_worker import VoiceWorker

EMBED_DIR = Path(__file__).resolve().parent.parent / "embed_server"
TITLE = "odie-embed"  # what embed_server/server.py calls itself
MODEL = "google/embeddinggemma-2"
current: EmbedWorker | None = None  # the running server's worker (set by the app at startup; None with ODIE_EMBED=off)


def embed_port() -> int:
    return int(os.environ.get("ODIE_EMBED_PORT", "8772"))


class EmbedWorker(VoiceWorker):
    title = TITLE
    what = "local embeddings"
    port_setting = "ODIE_EMBED_PORT"

    def __init__(self, folder: Path = EMBED_DIR, port: int | None = None, cmd: list[str] | None = None, log: Path | None = None):
        super().__init__(folder=folder, port=port or embed_port(), cmd=cmd, log=log)

    def environment(self) -> dict[str, str]:
        """What the service needs besides Odie's own environment: how long to keep the model loaded when idle
        (ODIE_EMBED_IDLE_MINUTES in ~/.odie/.env, 15 by default), and a Hugging Face token when there is one (HF_TOKEN
        there too; the model is public, so none is needed).
          HF_TOKEN=hf_abc, nothing else set -> {"ODIE_EMBED_IDLE_MINUTES": "15", "HF_TOKEN": "hf_abc"}"""
        from odie import config
        env = {"ODIE_EMBED_IDLE_MINUTES": str(config.settings.embed_idle_minutes)}
        token = load_secret("HF_TOKEN")
        if token:
            env["HF_TOKEN"] = token
        return env
