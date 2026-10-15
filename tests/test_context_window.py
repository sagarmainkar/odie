import httpx

from odie.models import Provider, Selection, context_window, history_limit_for


def _sel(pid: str, model: str, base: str) -> Selection:
    return Selection(Provider(pid, pid, base, None, True), model, "chat")


async def test_lm_studio_reports_the_loaded_context():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v0/models/qwen3.8-27b-splash"
        return httpx.Response(200, json={"id": "qwen3.8-27b-splash", "max_context_length": 262144, "loaded_context_length": 75000})
    sel = _sel("lmstudio", "qwen3.8-27b-splash", "http://127.0.0.1:1234/v1")
    assert await context_window(sel, transport=httpx.MockTransport(handler)) == 75000


async def test_ollama_reports_the_model_context():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/show"
        return httpx.Response(200, json={"model_info": {"glm_dsa_moe.context_length": 1048576, "general.architecture": "glm"}})
    sel = _sel("ollama", "glm-5.3:cloud", "http://localhost:11434/v1")
    assert await context_window(sel, transport=httpx.MockTransport(handler)) == 1048576


async def test_unknown_or_unreachable_gives_none():
    boom = httpx.MockTransport(lambda req: httpx.Response(500))
    assert await context_window(_sel("lmstudio", "m", "http://127.0.0.1:1234/v1"), transport=boom) is None
    assert await context_window(_sel("custom1", "m", "https://example.org/v1"), transport=boom) is None


def test_the_history_limit_is_three_quarters_capped_at_300k():
    assert history_limit_for(75000) == 56250
    assert history_limit_for(1048576) == 300_000
    assert history_limit_for(None) == 50_000
    assert history_limit_for(4096) == 3072  # a small window must be followed, or the chat overflows before the cut
