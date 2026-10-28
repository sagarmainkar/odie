"""Odie's model layer (2026-10-14): ADK's LiteLlm for every provider. Odie says one word about thinking, "low" or
"medium" (effort_for), and litellm turns it into what each model wants: LM Studio and Ollama take the word as it is,
OpenAI's thinking models go to the Responses API with it, Claude gets adaptive thinking at that effort. litellm also
drops the settings a model refuses (drop_params): top_p on gpt-5, temperature while Claude thinks. Every request the
agent makes is saved as litellm got it (SavingClient), for reading the real prompt (scripts/last_prompt.sh)."""
from __future__ import annotations

import copy
import functools
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

from odie import config

log = logging.getLogger("odie.model")

# Room per reply for a thinking model's reasoning plus a long answer (a trip plan, a report). ADK's default of 4096
# cut glm-5.3 off mid-answer after ~3k tokens of thinking. Every provider Odie offers accepts 16k. A model that allows
# more gets 32k (reply_tokens_for): DeepSeek planned an explainer video for ~15k tokens and ran out before it wrote the
# tool call (16 Oct 2026).
REPLY_TOKENS = 16000
ROOMY_REPLY_TOKENS = 32000
# A background writer's turn (an explainer video's page): DeepSeek drafts the whole page in its thinking before it
# writes the call, and a rich 4-minute video's draft alone took all of 32k (16 Oct 2026); with 64k it passed first time.
WRITER_REPLY_TOKENS = 64000
# The names litellm's table knows each cloud provider's models by ("openai/gpt-4o-mini"). Not listed: a custom provider.
LOOKUP_PREFIX = {"openai": "openai/", "anthropic": "anthropic/", "gemini": "gemini/", "openrouter": "openrouter/"}
# Where a provider refused the roomy reply: model and address -> the room it gets from then on (REPLY_TOKENS).
_refused_room: dict[str, int] = {}
TIMEOUT_SECONDS = 180

# Claude signs each thought to the exact conversation it was made in. Sent back after Odie changed the system prompt
# (the "[4 steps left]" note late in a turn) or an earlier message, Claude refused the whole request. With this setting
# (an Anthropic beta of 2026-08-01) Claude drops the stale thought itself and answers (checked live 2026-10-14, Sonnet
# 5.5 and Opus 5.5). "summarized": the thoughts come back with text, so ADK can send them back between tool calls.
CLAUDE_THINKING = {"type": "adaptive", "display": "summarized", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
CLAUDE_BETA_HEADER = {"anthropic-beta": "thinking-binding-controls-2026-08-01"}


def effort_for(think_harder: bool) -> str:
    """The one word Odie says about thinking, the same to every model:
      think_harder False (every turn, chat or background)  -> "low"
      think_harder True  (the chat's "Think harder" toggle) -> "medium" """
    if think_harder:
        return "medium"
    return "low"


# Think harder on a local server, as words at the end of that turn's message (think_harder_words). Its wording follows
# the chat template's own line about effort (Qwen's: "Reasoning effort is set to low. Keep your thinking brief…").
THINK_HARDER_WORDS = ("[Think harder on this one: reasoning effort for this message is medium. Think carefully through "
                      "the task, check key assumptions and weigh alternatives before answering.]")
# The presets that run elsewhere: their reasoning_effort is real, and a changed one doesn't cost a local re-read.
CLOUD_PRESETS = ("openai", "anthropic", "gemini", "openrouter")


def runs_on_local_server(selection) -> bool:
    """Whether this chat model runs on a server whose prompt cache a changed reasoning_effort would throw away. The
    chat template writes the effort into the first lines of the system message, so a flip of Think harder re-reads the
    whole chat (27,752 tokens, 245 s before the first word, 28 Oct 2026). Such a selection always gets the same effort.
      lmstudio / gemma-4-26b-a4b-it-qat                           -> True
      a custom provider (an address the user added, like http://127.0.0.1:8001/v1) -> True
      ollama / gemma3:12b (a model on this machine)               -> True
      ollama / deepseek-v4.1-flash:cloud (Ollama runs it in its cloud: the effort is real there) -> False
      openai, anthropic, gemini, openrouter                       -> False"""
    provider_id = selection.provider.id
    if provider_id in CLOUD_PRESETS:
        return False
    if provider_id == "ollama":
        runs_in_ollamas_cloud = selection.model.endswith(("-cloud", ":cloud"))
        return not runs_in_ollamas_cloud
    return True  # LM Studio, or a custom provider: an OpenAI-style server the user runs or chose


def chat_effort_think_harder(selection, think_harder: bool) -> bool:
    """Whether the chat model is built with the higher effort: Think harder on, on a model whose effort is real. A local
    server always gets the lower one (Think harder goes as words instead, think_harder_words).
      openai / gpt-5.5, Think harder on        -> True  ("medium")
      openai / gpt-5.5, Think harder off       -> False ("low")
      lmstudio / any model, Think harder on    -> False ("low", and the words in the message)"""
    if runs_on_local_server(selection):
        return False
    return think_harder


def think_harder_words(selection, think_harder: bool) -> str:
    """What goes at the very end of this turn's message for Think harder, with a line break before it: the words on a
    local server with it on, nothing otherwise (a cloud model gets "medium" as its effort).
      lmstudio, Think harder on    -> "\n[Think harder on this one: reasoning effort for this message is medium. …]"
      lmstudio, Think harder off   -> ""
      openai, Think harder on      -> "" """
    if not think_harder:
        return ""
    if not runs_on_local_server(selection):
        return ""
    return "\n" + THINK_HARDER_WORDS


@functools.cache
def _known_output_limit(name: str) -> int:
    """The most tokens litellm's table says the model may write in one reply, or 0 when it doesn't know the model."""
    try:
        info = _litellm().get_model_info(name)
    except Exception:  # noqa: BLE001 - litellm raises when the model isn't in its table
        return 0
    return int(info.get("max_output_tokens") or 0)


def reply_tokens_for(selection, wanted: int = ROOMY_REPLY_TOKENS) -> int:
    """How many tokens a reply may use: the room wanted (32k for a chat turn, 64k for a background writer) where the
    model allows it, its own limit where that's lower, 16k (which every provider accepts) where nothing is known.
      LM Studio or Ollama (the user's own server, or Ollama's cloud models) -> the room wanted: 32000, or 64000
      OpenAI gpt-4o-mini (litellm: at most 16,384)                          -> 16384
      Claude Sonnet 4.5 (litellm: 64,000)                                   -> 32000; a writer: 64000
      a custom provider, or a model litellm doesn't know                     -> 16000"""
    provider = selection.provider
    if provider.id in ("lmstudio", "ollama"):
        return wanted
    prefix = LOOKUP_PREFIX.get(provider.id)
    if prefix is None:
        return REPLY_TOKENS
    limit = _known_output_limit(prefix + selection.model)
    if not limit:
        return REPLY_TOKENS
    return min(wanted, limit)


def refused_for_reply_room(error: Exception) -> bool:
    """Whether a provider refused the request because it asked for more reply room than the model allows.
      BadRequestError "max_tokens is too large: 32000. This model supports at most 16384 completion tokens" -> True
      BadRequestError "messages: roles must alternate"                                                   -> False
      any other kind of error                                                                            -> False"""
    if not isinstance(error, _litellm().BadRequestError):
        return False
    text = str(error).lower()
    names_the_setting = any(name in text for name in ("max_tokens", "max_completion_tokens", "max_output_tokens"))
    return names_the_setting or "completion tokens" in text


async def with_reply_room(call, kwargs: dict[str, Any]):
    """call(**kwargs), where a provider that refused the roomy reply once gets REPLY_TOKENS from then on: the first
    refusal is retried at once with REPLY_TOKENS and remembered for that model and address."""
    key = f"{kwargs.get('model')}@{kwargs.get('api_base', '')}"
    asked = kwargs.get("max_tokens") or 0
    if key in _refused_room and asked > _refused_room[key]:
        kwargs = {**kwargs, "max_tokens": _refused_room[key]}
        asked = kwargs["max_tokens"]
    try:
        return await call(**kwargs)
    except Exception as e:
        if asked <= REPLY_TOKENS or not refused_for_reply_room(e):
            raise
        log.warning("%s refused a %s-token reply; asking for %s from now on", kwargs.get("model"), asked, REPLY_TOKENS)
        _refused_room[key] = REPLY_TOKENS
        return await call(**{**kwargs, "max_tokens": REPLY_TOKENS})


def litellm_model(selection) -> str:
    """The model name litellm routes on: Claude speaks its own API; everything else speaks the OpenAI chat API (LM Studio,
    Ollama, OpenAI, OpenRouter, Gemini's compatible endpoint, a custom provider).
      anthropic / claude-sonnet-5-5      -> "anthropic/claude-sonnet-5-5"
      lmstudio  / gemma-4-26b-a4b-it-qat -> "openai/gemma-4-26b-a4b-it-qat" """
    if selection.provider.id == "anthropic":
        return "anthropic/" + selection.model
    return "openai/" + selection.model


def address_of(selection) -> dict[str, str]:
    """Where litellm sends the request, and with what key. OpenAI and Claude on their own default address get no api_base,
    so litellm keeps its own default and its own routing (OpenAI's thinking models go to the Responses API). Any other
    address (a proxy, another computer, every other provider) is passed along; Claude's goes without /v1, litellm adds it.
      LM Studio at http://localhost:1234/v1, key "lm-studio" -> {"api_base": "http://localhost:1234/v1", "api_key": "lm-studio"}
      Ollama, no key                                          -> {"api_base": "http://localhost:11434/v1", "api_key": "none"}
      OpenAI on api.openai.com                                -> {"api_key": "sk-…"}
      Claude moved to https://claude.proxy/v1                 -> {"api_base": "https://claude.proxy", "api_key": "sk-…"}"""
    from odie.models import PRESET_BY_ID
    provider = selection.provider
    out = {"api_key": provider.api_key or "none"}  # a local server takes any key, and litellm wants one
    preset = PRESET_BY_ID.get(provider.id)
    on_its_own_address = preset is not None and provider.base_url == preset.base_url
    if on_its_own_address and provider.id in ("openai", "anthropic"):
        return out
    base_url = provider.base_url
    if provider.id == "anthropic":
        base_url = base_url.removesuffix("/v1")
    return {"api_base": base_url, **out}


def completion_args(selection, think_harder: bool = False, room: int = ROOMY_REPLY_TOKENS) -> dict[str, Any]:
    """Everything a litellm call carries for this Selection (odie.models), the agent's and the one-shot ones alike.
    room: the reply room wanted (reply_tokens_for decides what the model gets)."""
    args: dict[str, Any] = {
        "model": litellm_model(selection),
        **address_of(selection),
        "reasoning_effort": effort_for(think_harder),
        "max_tokens": reply_tokens_for(selection, room),
        "timeout": TIMEOUT_SECONDS,
        "drop_params": True,
    }
    if selection.provider.id == "anthropic":
        args["thinking"] = copy.deepcopy(CLAUDE_THINKING)
        args["extra_headers"] = dict(CLAUDE_BETA_HEADER)
    return args


def save_request(kwargs: dict[str, Any], folder: Path, keep: int = 10) -> None:
    """Keep the last few requests as litellm got them, for reading the real prompt. The key and the headers are left out;
    image data is replaced by its size. Never raises: a debugging aid must not break a turn."""
    try:
        body = copy.deepcopy({k: v for k, v in kwargs.items() if k not in ("api_key", "extra_headers")})
        for m in body.get("messages") or []:
            for part in m.get("content") if isinstance(m.get("content"), list) else []:
                url = (part.get("image_url") or {}).get("url", "") if isinstance(part, dict) else ""
                if url.startswith("data:"):
                    part["image_url"]["url"] = f"[image omitted, {len(url)} characters of base64]"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
        (folder / f"{stamp}.json").write_text(json.dumps(body, indent=1, ensure_ascii=False, default=str))
        for old in sorted(folder.glob("*.json"))[:-keep]:
            old.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        log.debug("save_request failed", exc_info=True)


class SavingClient(LiteLLMClient):
    """ADK's seam to litellm, with every request saved first (save_request), exactly as litellm is handed it."""

    async def acompletion(self, model, messages, tools, **kwargs):
        save_request({"model": model, "messages": messages, "tools": tools, **kwargs}, config.settings.data_dir / "requests")
        send = super().acompletion

        async def call(**args):
            args.pop("model")  # named here only so with_reply_room knows which model it is
            return await send(model, messages, tools, **args)

        return await with_reply_room(call, {"model": model, **kwargs})


def _litellm():
    """litellm, imported the way ADK does (no .env autoload) and without its banners: it prints a provider list and a
    feedback plea on every error, and Odie's log has the error already."""
    os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
    import litellm
    litellm.suppress_debug_info = True
    return litellm


def model_for(selection, think_harder: bool, room: int = ROOMY_REPLY_TOKENS) -> LiteLlm:
    """The ADK model for a Selection (odie.models). think_harder: the chat's "Think harder" toggle; background turns pass
    False. room: the reply room wanted (a background writer asks for WRITER_REPLY_TOKENS). The same model object serves
    a whole chat until the selection or the toggle changes (odie.app.runner)."""
    _litellm()
    return LiteLlm(llm_client=SavingClient(), **completion_args(selection, think_harder, room))


async def complete(selection, messages: list[dict], tools: list[dict] | None = None, think_harder: bool = False, transport=None,
                   **opts):
    """One request outside the agent (the brief, memory review, summaries, the brain check, the setup chat), through the
    same litellm call the agent uses. opts: temperature, max_tokens, timeout and the like; litellm drops what the model
    refuses. transport: a test's fake server (httpx.MockTransport); litellm's HTTP goes through it. Returns litellm's
    reply in OpenAI's shape: reply.choices[0].message."""
    args = completion_args(selection, think_harder) | opts
    if tools:
        args["tools"] = tools
    if transport is not None:
        args["client"] = _client_over(selection, args, transport)
    async def call(**request):
        return await _litellm().acompletion(messages=messages, **request)

    return await with_reply_room(call, args)


def _client_over(selection, args: dict[str, Any], transport):
    """The HTTP client litellm uses for this provider, over a fake server: the OpenAI library's client for everything
    that speaks the OpenAI API, litellm's own handler for Claude. No retries: a test's 500 is a 500."""
    import httpx
    if selection.provider.id == "anthropic":
        from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
        handler = AsyncHTTPHandler()
        handler.client = httpx.AsyncClient(transport=transport)
        return handler
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=args["api_key"], base_url=args.get("api_base") or "https://api.openai.com/v1", max_retries=0,
                       http_client=httpx.AsyncClient(transport=transport))
