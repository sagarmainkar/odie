"""How much of each model reply's input came from the provider's prompt cache (2026-10-08). Every adapter reports it
in the same place (usage_metadata.cached_content_token_count), so this works for whichever provider is chosen; Settings
shows the latest, to see whether caching works."""
from __future__ import annotations

from datetime import datetime

from google.adk.agents.context_cache_config import ContextCacheConfig

KEY = "model.usage"
# One switch for all of Odie: Claude marks its prompt for the cache; Gemini would make a server-side cache; providers
# that cache a repeated start by themselves (OpenAI-style) ignore it. Half an hour outlives a pause in a chat.
CACHE = ContextCacheConfig(ttl_seconds=1800)


def record(store, usage, model: str | None = None) -> None:
    """Keep the latest reply's token counts (no text, only numbers)."""
    if store is None or usage is None or not getattr(usage, "prompt_token_count", None):
        return
    store.set_setting(KEY, {"input": usage.prompt_token_count, "cached": usage.cached_content_token_count or 0,
                            "output": usage.candidates_token_count or 0, "model": model,
                            "at": datetime.now().astimezone().isoformat(timespec="seconds")})


def last_usage(store) -> dict | None:
    return store.get_setting(KEY) or None
