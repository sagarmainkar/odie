"""Two fake model servers that speak the real wire formats, for the shared model tests (tests/test_model_contract.py):
OpenAI chat completions (JSON, or SSE chunks when streaming) and Anthropic messages (JSON, or SSE events). Each plays a
script of replies, a text or a tool call, and keeps every request body it got. The real SDK clients talk to them
through a mock transport, so the adapters run exactly as they do against the real APIs.

The Anthropic one signs its thinking as Claude does: the signature is bound to the system prompt, the tools and every
message before the reply (thoughts and cache marks aside), and a thought sent back under anything else is refused with
Claude's own 400, unless the request carries the block_binding setting (and its beta header), in which case the stale
thought is dropped and the request answered, as Claude does (checked live 2026-10-14). Each thought also records the one
before it in the request it answered, so thoughts may be dropped from the front of the conversation but not from the
middle (Anthropic's "preserved thinking" chain). Its thinking carries text, as Claude's does with display "summarized"."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class Reply:
    text: str = ""
    tool: str = ""          # a tool call to this tool
    args: dict = field(default_factory=dict)  # ...with these arguments
    thinking: bool = False  # Claude only: a signed thinking block before it
    cached: int = 90        # input tokens the provider says came from its cache
    prompt: int = 100


@dataclass
class Script:
    replies: list[Reply]
    bodies: list[dict] = field(default_factory=list)   # every request answered
    refused: list[dict] = field(default_factory=list)  # every request refused with a 400
    dropped: list[str] = field(default_factory=list)   # Claude's reason for each stale thought it dropped instead (block_binding)
    before: dict = field(default_factory=dict)          # a thought's signature -> the thought before it when made

    def next(self, body: dict) -> Reply:
        self.bodies.append(body)
        return self.replies[len(self.bodies) - 1]


def _sse(events: list[tuple[str | None, dict | str]]) -> bytes:
    out = []
    for name, data in events:
        if name:
            out.append(f"event: {name}")
        out.append("data: " + (data if isinstance(data, str) else json.dumps(data)))
        out.append("")
    return ("\n".join(out) + "\n").encode()


def openai_handler(script: Script, httpx):
    def handle(req):
        body = json.loads(req.content)
        r = script.next(body)
        usage = {"prompt_tokens": r.prompt, "completion_tokens": 5, "total_tokens": r.prompt + 5,
                 "prompt_tokens_details": {"cached_tokens": r.cached}}
        call = [{"index": 0, "id": f"call_{len(script.bodies)}", "type": "function", "function": {"name": r.tool, "arguments": json.dumps(r.args)}}]
        if not body.get("stream"):
            msg = {"role": "assistant", "content": r.text or None, **({"tool_calls": [{k: v for k, v in call[0].items() if k != "index"}]} if r.tool else {})}
            return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 0, "model": body["model"],
                                             "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if r.tool else "stop"}],
                                             "usage": usage})
        chunk = lambda delta, finish=None: {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": body["model"],  # noqa: E731
                                            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        events = [(None, chunk({"role": "assistant", "tool_calls": call} if r.tool else {"role": "assistant", "content": r.text})),
                  (None, chunk({}, "tool_calls" if r.tool else "stop")),
                  (None, {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": body["model"], "choices": [], "usage": usage}),
                  (None, "[DONE]")]
        return httpx.Response(200, content=_sse(events), headers={"content-type": "text/event-stream"})
    return handle


def _without_marks(value):
    """value minus every cache_control mark (where the marks sit changes from request to request)."""
    if isinstance(value, dict):
        return {k: _without_marks(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_without_marks(v) for v in value]
    return value


def _is_thought(block) -> bool:
    return isinstance(block, dict) and block.get("type") in ("thinking", "redacted_thinking")


def _blocks(content) -> list:
    """A message's content as blocks, thoughts and cache marks aside: "hi" and [{"type": "text", "text": "hi"}] are the
    same words (litellm writes the latest message as blocks while it carries the cache mark, then as a string once the
    mark has moved on), and Claude binds a thought to the words, not the shape."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [_without_marks(b) for b in content if not _is_thought(b)]


def signature_for(body: dict, upto: int) -> str:
    """The fake's signature for a thought in the reply that follows body's first `upto` messages."""
    before = []
    for m in body["messages"][:upto]:
        before.append({"role": m["role"], "content": _blocks(m["content"])})
    bound = json.dumps(_without_marks([body.get("system"), body.get("tools"), before]), sort_keys=True)
    plain = "sig-" + hashlib.sha256(bound.encode()).hexdigest()[:16]
    return base64.b64encode(plain.encode()).decode()  # base64, as Claude's are: ADK decodes a signature and encodes it again


def _signatures(body: dict) -> list[str]:
    """The thoughts a request sends back, in order, by signature."""
    return [b.get("signature") or b.get("data") for m in body["messages"]
            for b in (m["content"] if isinstance(m["content"], list) else []) if _is_thought(b)]


def first_bad_thought(body: dict, before: dict | None = None) -> str | None:
    """Claude's 400 message for the first thought sent back that doesn't match its place, or None. With `before`
    (signature -> the thought before it when it was made), a thought whose predecessor was dropped while the thought
    itself stayed is refused too: only a leading run of thoughts may go."""
    sent = []
    for i, m in enumerate(body["messages"]):
        for j, b in enumerate(m["content"] if isinstance(m["content"], list) else []):
            if not _is_thought(b):
                continue
            signature = b.get("signature") or b.get("data")
            broken_chain = before is not None and sent and before.get(signature) != sent[-1]
            if signature != signature_for(body, i) or broken_chain:
                return (f"messages.{i}.content.{j}: Invalid `signature` in `{b['type']}` block. The block is bound to a "
                        "different conversation. Remove the block, or send it back unchanged.")
            sent.append(signature)
    return None


def _refuse(httpx, message: str):
    return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": message}})


BINDING_BETA = "thinking-binding-controls-2026-08-01"


def drops_stale_thoughts(body: dict, headers) -> bool:
    """Whether the request asked Claude to drop a thought that no longer fits instead of refusing: the block_binding
    setting in `thinking`, and the beta header that unlocks it. Both -> True; the setting alone -> False (the real API
    then answers 400 for the unknown field; here it is treated as refusing the thought)."""
    binding = (body.get("thinking") or {}).get("block_binding") or {}
    asked = binding.get("prefix_mismatch_behavior") == "drop_block"
    unlocked = BINDING_BETA in (headers.get("anthropic-beta") or "")
    return asked and unlocked


def anthropic_handler(script: Script, httpx):
    def handle(req):
        body = json.loads(req.content)
        bad = first_bad_thought(body, script.before)
        if bad and drops_stale_thoughts(body, req.headers):
            script.dropped.append(bad)
        elif bad:
            script.refused.append(body)
            return _refuse(httpx, bad)
        r = script.next(body)
        usage = {"input_tokens": r.prompt - r.cached, "output_tokens": 5, "cache_read_input_tokens": r.cached, "cache_creation_input_tokens": 0}
        blocks = []
        if r.thinking:
            signature = signature_for(body, len(body["messages"]))
            earlier = _signatures(body)
            script.before[signature] = earlier[-1] if earlier else None
            blocks.append({"type": "thinking", "thinking": "Let me think.", "signature": signature})
        if r.text:
            blocks.append({"type": "text", "text": r.text})
        if r.tool:
            blocks.append({"type": "tool_use", "id": f"toolu_{len(script.bodies)}", "name": r.tool, "input": r.args})
        stop = "tool_use" if r.tool else "end_turn"
        if not body.get("stream"):
            return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "content": blocks,
                                             "stop_reason": stop, "stop_sequence": None, "usage": usage})
        events = [("message_start", {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                                                         "content": [], "stop_reason": None, "stop_sequence": None, "usage": usage}})]
        for i, b in enumerate(blocks):
            if b["type"] == "thinking":  # the text streams first, then the signature, as Claude sends it
                events += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": b["thinking"]}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": b["signature"]}})]
            elif b["type"] == "text":
                events += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}})]
            else:
                events += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": {**b, "input": {}}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}})]
            events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
        events += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 5}}),
                   ("message_stop", {"type": "message_stop"})]
        return httpx.Response(200, content=_sse(events), headers={"content-type": "text/event-stream"})
    return handle
