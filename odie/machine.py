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


def _asked_for(value: str) -> bool:
    """Whether a switch's words ask for a service that is off unless asked: "on", "1" and "yes" turn it on; anything
    else, or nothing, leaves it off. "on" -> True; "" -> False; "off" -> False."""
    return value.strip().lower() in ("on", "1", "yes")


def local_voice_wanted() -> bool:
    """Whether Odie's own voice (Kokoro) is meant to run here. ODIE_VOICE unset on an M2 -> True; ODIE_VOICE=off, which
    the installer sets on an Intel Mac -> False, and Kokoro is offered nowhere."""
    return _wanted(os.environ.get("ODIE_VOICE", ""))


def local_embeddings_wanted() -> bool:
    """Whether Odie's own embedding service is meant to run here: only when asked for (ODIE_EMBED=on at install).
    Since 25 Oct 2026 it is off by default: EmbeddingGemma 2 on Ollama reads notes and pictures the same way with no
    download or torch of Odie's own. ODIE_EMBED unset or off -> False, and Odie's service is offered nowhere;
    ODIE_EMBED=on -> True."""
    return _asked_for(os.environ.get("ODIE_EMBED", ""))
