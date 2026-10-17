"""The model layer (2026-10-14): ADK's LiteLlm for every provider. Odie says one word about thinking, "low" or "medium",
and litellm turns it into whatever each model wants; Claude also gets the setting that makes it drop a thought whose
conversation changed, instead of refusing the request."""
import json

from google.adk.models.lite_llm import LiteLlm

from odie.agent.model import (CLAUDE_BETA_HEADER, CLAUDE_THINKING, REPLY_TOKENS, SavingClient, address_of, effort_for, litellm_model,
                              model_for, save_request)
from odie.models import Provider, Selection


def _sel(pid: str, model: str, base: str = "https://api.example/v1", key: str | None = "sk-test") -> Selection:
    return Selection(Provider(pid, pid.title(), base, key, pid in ("lmstudio", "ollama")), model, "chat")


def test_the_effort_word_for_a_turn():
    assert effort_for(think_harder=False) == "low"      # every turn, chat or background
    assert effort_for(think_harder=True) == "medium"    # the chat's "Think harder" toggle


def test_litellm_routes_on_the_provider_kind():
    assert litellm_model(_sel("anthropic", "claude-sonnet-5-5")) == "anthropic/claude-sonnet-5-5"
    assert litellm_model(_sel("lmstudio", "gemma-4-26b-a4b-it-qat")) == "openai/gemma-4-26b-a4b-it-qat"
    assert litellm_model(_sel("ollama", "glm-5.3-flash:cloud")) == "openai/glm-5.3-flash:cloud"
    assert litellm_model(_sel("openai", "gpt-5.5")) == "openai/gpt-5.5"
    assert litellm_model(_sel("my-box", "foo")) == "openai/foo"   # a custom provider speaks the OpenAI API too


def test_the_address_is_the_providers_own():
    assert address_of(_sel("lmstudio", "gemma", base="http://localhost:1234/v1", key="lm-studio")) == {"api_base": "http://localhost:1234/v1", "api_key": "lm-studio"}
    assert address_of(_sel("ollama", "glm", base="http://localhost:11434/v1", key=None)) == {"api_base": "http://localhost:11434/v1", "api_key": "none"}
    assert address_of(_sel("openai", "gpt-5.5", base="https://api.openai.com/v1")) == {"api_key": "sk-test"}            # litellm's own default
    assert address_of(_sel("openai", "gpt-5.5", base="https://proxy.example/v1")) == {"api_base": "https://proxy.example/v1", "api_key": "sk-test"}
    assert address_of(_sel("anthropic", "claude-sonnet-5-5", base="https://api.anthropic.com/v1")) == {"api_key": "sk-test"}
    assert address_of(_sel("anthropic", "claude-sonnet-5-5", base="https://claude.proxy/v1")) == {"api_base": "https://claude.proxy", "api_key": "sk-test"}


def test_model_for_builds_litellm_with_the_effort_word():
    llm = model_for(_sel("ollama", "glm-5.3-flash:cloud", base="http://localhost:11434/v1", key=None), think_harder=False)
    assert isinstance(llm, LiteLlm) and llm.model == "openai/glm-5.3-flash:cloud"
    args = llm._additional_args
    assert args["reasoning_effort"] == "low"
    assert args["drop_params"] is True                 # litellm drops only what a model refuses (top_p on gpt-5, temperature with Claude thinking)
    assert args["max_tokens"] == 32000                 # Ollama: room for long thinking plus a long answer (reply_tokens_for)
    assert args["api_base"] == "http://localhost:11434/v1" and args["api_key"] == "none"
    assert "thinking" not in args and "extra_headers" not in args
    assert isinstance(llm.llm_client, SavingClient)
    assert model_for(_sel("ollama", "glm-5.3-flash:cloud"), think_harder=True)._additional_args["reasoning_effort"] == "medium"


def test_claude_also_gets_the_binding_that_drops_a_stale_thought():
    args = model_for(_sel("anthropic", "claude-opus-5-5", base="https://api.anthropic.com/v1"), think_harder=False)._additional_args
    assert args["reasoning_effort"] == "low" and "api_base" not in args
    assert args["thinking"] == CLAUDE_THINKING == {"type": "adaptive", "display": "summarized",
                                                   "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    assert args["extra_headers"] == CLAUDE_BETA_HEADER == {"anthropic-beta": "thinking-binding-controls-2026-08-01"}


def test_save_request_keeps_newest_and_shrinks_images(tmp_path):
    img = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 5000}}
    for i in range(12):
        save_request({"model": "m", "messages": [{"role": "user", "content": [{"type": "text", "text": f"hi {i}"}, img]}]}, tmp_path, keep=10)
    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 10
    body = json.loads(files[-1].read_text())
    assert body["messages"][0]["content"][0]["text"] == "hi 11"
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("[image omitted")


def test_save_request_never_writes_a_key(tmp_path):
    save_request({"model": "m", "messages": [], "api_key": "sk-secret", "extra_headers": {"anthropic-beta": "x"}, "reasoning_effort": "low"}, tmp_path)
    text = next(tmp_path.glob("*.json")).read_text()
    body = json.loads(text)
    assert "sk-secret" not in text and "api_key" not in body and "extra_headers" not in body
    assert body["reasoning_effort"] == "low"   # the settings that matter for reading the prompt stay


async def test_every_request_is_saved_as_litellm_gets_it(isolated_settings, monkeypatch):
    """The saver sits on ADK's own seam (llm_client), so it sees exactly what litellm is handed, and hands it on unchanged."""
    from google.adk.models import lite_llm
    seen = []

    async def acompletion(**kw):
        seen.append(kw)
        return "reply"
    lite_llm._ensure_litellm_imported()
    monkeypatch.setattr(lite_llm, "acompletion", acompletion)
    out = await SavingClient().acompletion("openai/m", [{"role": "user", "content": "hi"}], [], api_key="sk-secret", reasoning_effort="low")
    assert out == "reply" and seen[0]["api_key"] == "sk-secret" and seen[0]["model"] == "openai/m"
    files = list((isolated_settings.data_dir / "requests").glob("*.json"))
    assert len(files) == 1 and "sk-secret" not in files[0].read_text()
    body = json.loads(files[0].read_text())
    assert body["model"] == "openai/m" and body["messages"][0]["content"] == "hi" and body["reasoning_effort"] == "low"


async def test_a_one_shot_call_goes_through_litellm_with_the_same_words():
    """complete(): the brief, the brain check and the setup chat use it. Over a fake server: the key goes as a Bearer
    header, the effort word and the caller's sampling go in the body, and the reply comes back in OpenAI's shape."""
    import httpx

    from odie.agent.model import complete
    seen = []

    def handler(req):
        seen.append((req, json.loads(req.content)))
        return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 0, "model": "glm-test",
                                         "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello."}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})
    sel = _sel("ollama", "glm-test", base="http://localhost:11434/v1", key="sk-k")
    reply = await complete(sel, [{"role": "user", "content": "hi"}], temperature=0.3, max_tokens=100, transport=httpx.MockTransport(handler))
    assert reply.choices[0].message.content == "Hello."
    req, body = seen[0]
    assert str(req.url) == "http://localhost:11434/v1/chat/completions" and req.headers["authorization"] == "Bearer sk-k"
    assert body["reasoning_effort"] == "low" and body["temperature"] == 0.3 and body["max_tokens"] == 100 and body["model"] == "glm-test"


# Room per reply (16 Oct 2026): a thinking model planned an explainer video for ~15k tokens and ran out of its 16k
# before it wrote the tool call. Models that allow it get 32k; the ceiling follows each model's own limit, looked up
# in litellm's table (the real one here), and stays at 16k where nothing is known.

def test_room_per_reply_follows_the_models_own_limit():
    from odie.agent.model import ROOMY_REPLY_TOKENS, reply_tokens_for
    assert ROOMY_REPLY_TOKENS == 32000
    assert reply_tokens_for(_sel("lmstudio", "gemma-4-26b-a4b-it-qat", base="http://localhost:1234/v1")) == 32000
    assert reply_tokens_for(_sel("ollama", "deepseek-v4.1-flash:cloud", base="http://localhost:11434/v1")) == 32000
    assert reply_tokens_for(_sel("openai", "gpt-4o-mini")) == 16384           # its own limit, below 32k
    assert reply_tokens_for(_sel("anthropic", "claude-sonnet-4-5")) == 32000   # allows 64k; 32k is plenty
    assert reply_tokens_for(_sel("gemini", "gemini-2.5-flash")) == 32000
    assert reply_tokens_for(_sel("openrouter", "someone/unknown-model")) == REPLY_TOKENS == 16000
    assert reply_tokens_for(_sel("custom-box", "my-model")) == 16000


def test_every_request_carries_the_models_room():
    from odie.agent.model import completion_args
    assert completion_args(_sel("openai", "gpt-4o-mini"))["max_tokens"] == 16384
    assert completion_args(_sel("ollama", "deepseek-v4.1-flash:cloud", base="http://localhost:11434/v1"))["max_tokens"] == 32000


def test_a_refusal_over_the_reply_room_is_recognised():
    import litellm

    from odie.agent.model import refused_for_reply_room
    too_big = litellm.BadRequestError("max_tokens is too large: 32000. This model supports at most 16384 completion tokens",
                                      model="x", llm_provider="openai")
    other = litellm.BadRequestError("messages: roles must alternate", model="x", llm_provider="openai")
    assert refused_for_reply_room(too_big) and not refused_for_reply_room(other)
    assert not refused_for_reply_room(ValueError("max_tokens is too large"))   # only a provider's refusal counts


async def test_a_provider_that_refuses_32k_gets_16k_and_is_remembered():
    import httpx

    from odie.agent.model import complete
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if body["max_tokens"] > 16000:
            return httpx.Response(400, json={"error": {"message": "max_tokens is too large: 32000. This model supports at most "
                                                                  "16000 completion tokens.", "type": "invalid_request_error",
                                                       "param": "max_tokens", "code": "invalid_value"}})
        return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 0, "model": "box-model",
                                         "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi."},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})
    sel = _sel("ollama", "box-model", base="http://localhost:11434/v1")
    first = await complete(sel, [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert first.choices[0].message.content == "Hi."
    assert [b["max_tokens"] for b in bodies] == [32000, 16000]          # refused, then the retry at 16k
    await complete(sel, [{"role": "user", "content": "again"}], transport=httpx.MockTransport(handler))
    assert bodies[-1]["max_tokens"] == 16000 and len(bodies) == 3       # remembered: no second refusal


def test_a_background_writer_gets_more_room_where_the_model_allows_it():
    # A rich 4-minute video's page drafted in DeepSeek's thinking took all of 32k; the writer's turn asks for 64k.
    from odie.agent.model import WRITER_REPLY_TOKENS, completion_args, reply_tokens_for
    assert WRITER_REPLY_TOKENS == 64000
    assert reply_tokens_for(_sel("ollama", "deepseek-v4.1-flash:cloud", base="http://localhost:11434/v1"), WRITER_REPLY_TOKENS) == 64000
    assert reply_tokens_for(_sel("anthropic", "claude-sonnet-4-5"), WRITER_REPLY_TOKENS) == 64000
    assert reply_tokens_for(_sel("openai", "gpt-4o-mini"), WRITER_REPLY_TOKENS) == 16384     # its own limit still wins
    assert reply_tokens_for(_sel("custom-box", "my-model"), WRITER_REPLY_TOKENS) == 16000
    assert completion_args(_sel("ollama", "m", base="http://localhost:11434/v1"))["max_tokens"] == 32000  # a chat turn
