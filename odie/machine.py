"""What this machine runs of Odie's own services: the local voice worker (Kokoro, on MLX, which only exists for Apple
Silicon) and the local embedding service (EmbeddingGemma 2 on PyTorch, which has no Intel Mac builds). The installer
sets ODIE_VOICE=off and ODIE_EMBED=off on a Mac that can't run them (an Intel Mac, 20 Oct 2026) and the service keeps
those words; anyone can set them by hand too. Everything that offers Kokoro or EmbeddingGemma 2 (setup, Settings, the
voice routes, the workers' start) asks here first, so a machine without them never shows them."""
import os


def _wanted(value: str) -> bool:
    """Whether a switch's words leave a service on: "off", "0" and "no" turn it off; anything else, or nothing, keeps
    it on, the same words odie.cli reads at install. "off" -> False; "" -> True; "on" -> True."""
    return value.strip().lower() not in ("off", "0", "no")


def local_voice_wanted() -> bool:
    """Whether Odie's own voice (Kokoro) is meant to run here. ODIE_VOICE unset on an M2 -> True; ODIE_VOICE=off, which
    the installer sets on an Intel Mac -> False, and Kokoro is offered nowhere."""
    return _wanted(os.environ.get("ODIE_VOICE", ""))


def local_embeddings_wanted() -> bool:
    """Whether Odie's own embedding service is meant to run here. ODIE_EMBED unset -> True; ODIE_EMBED=off, the
    installer's choice on an Intel Mac -> False, and EmbeddingGemma 2 is offered nowhere."""
    return _wanted(os.environ.get("ODIE_EMBED", ""))
