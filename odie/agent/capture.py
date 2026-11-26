"""Keeping model calls to train a smaller model on (ODIE_CAPTURE=1 in Odie's .env; off by default). Each call the agent
or a one-off request makes is kept with the reply it got, as one JSON line in <data>/training/<day>.jsonl.gz:
  {"at": "...", "model": "openai/deepseek-v4.1-flash:cloud", "system": "3f2a…", "tools": "9c1e…",
   "messages": [...the turn's messages, the system prompt left out...],
   "reply": {"text": "...", "tool_calls": [{"name": "task_add", "arguments": "{...}"}]}, "usage": {...}}
The long parts every call repeats (the system prompt, the tool list) are kept once each, as
<data>/training/parts/<hash>.json, and a line names them by hash: a day of calls stays megabytes, not gigabytes.
Images are left out (their size stands in). Nothing here leaves the Mac. Never raises: keeping a call must not break it.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from odie import config

log = logging.getLogger(__name__)


def on() -> bool:
    """Whether model calls are kept: ODIE_CAPTURE=1 -> True; unset or anything else -> False."""
    return config.settings.capture


def folder() -> Path:
    return config.settings.data_dir / "training"


def forget_all() -> None:
    """Removes every kept call and part. Like the saved requests they carry no thread id, so when one thread's words
    must go (a personality is deleted) they all go."""
    import shutil
    shutil.rmtree(folder(), ignore_errors=True)


def without_images(messages: list[dict]) -> list[dict]:
    """The messages with each inline image replaced by its size, so a kept call stays text. The list given is not
    changed. [{"content": [{"image_url": {"url": "data:image/png;base64,AAAA"}}]}] ->
    [{"content": [{"image_url": {"url": "[image omitted, 26 characters of base64]"}}]}]"""
    kept = json.loads(json.dumps(messages, default=str))
    for message in kept:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            image = part.get("image_url") or {}
            url = image.get("url", "") if isinstance(image, dict) else ""
            if url.startswith("data:"):
                image["url"] = f"[image omitted, {len(url)} characters of base64]"
    return kept


def _kept_once(thing: Any) -> str | None:
    """Keeps a long repeated part (a system prompt, a tool list) once, and returns its hash; None for nothing."""
    if not thing:
        return None
    text = json.dumps(thing, ensure_ascii=False, sort_keys=True, default=str)
    name = hashlib.sha256(text.encode()).hexdigest()[:16]
    path = folder() / "parts" / f"{name}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return name


def keep(model: str, messages: list[dict], tools: list | None, reply: dict, usage: Any = None) -> None:
    """Writes one call and its reply to today's file. The system message goes to parts/ (by hash), as do the tools."""
    try:
        system = [m for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        line = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "model": model,
            "system": _kept_once(without_images(system)),
            "tools": _kept_once(tools),
            "messages": without_images(rest),
            "reply": reply,
            "usage": _plain(usage),
        }
        folder().mkdir(parents=True, exist_ok=True)
        day = folder() / f"{time.strftime('%Y-%m-%d')}.jsonl.gz"
        with gzip.open(day, "at", encoding="utf-8") as out:  # each append is its own gzip member: one file, readable whole
            out.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001
        log.debug("keeping a model call failed", exc_info=True)


def _plain(usage: Any) -> dict | None:
    """litellm's usage object as a plain dict (None when there is none)."""
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    dump = getattr(usage, "model_dump", None)
    if dump is not None:
        return dump()
    return None


def reply_of(response: Any) -> dict:
    """What a whole (not streamed) reply said: its text and the tools it called.
    A reply "Done." calling task_add({"title": "x"}) -> {"text": "Done.", "tool_calls": [{"name": "task_add",
    "arguments": "{\"title\": \"x\"}"}]}"""
    message = response.choices[0].message
    calls = []
    for call in getattr(message, "tool_calls", None) or []:
        calls.append({"name": call.function.name, "arguments": call.function.arguments})
    return {"text": message.content or "", "tool_calls": calls}


class StreamedReply:
    """A streamed reply put back together from its pieces: the text, and each tool call's name and arguments (which
    arrive in fragments, numbered by their index)."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.calls: dict[int, dict] = {}
        self.usage: Any = None

    def add(self, part: Any) -> None:
        if getattr(part, "usage", None):
            self.usage = part.usage
        choices = getattr(part, "choices", None) or []
        if not choices:
            return
        delta = choices[0].delta
        if getattr(delta, "content", None):
            self.text.append(delta.content)
        for fragment in getattr(delta, "tool_calls", None) or []:
            index = fragment.index or 0
            call = self.calls.setdefault(index, {"name": "", "arguments": ""})
            function = fragment.function
            if function is None:
                continue
            if function.name:
                call["name"] += function.name
            if function.arguments:
                call["arguments"] += function.arguments

    def whole(self) -> dict:
        return {"text": "".join(self.text), "tool_calls": [self.calls[i] for i in sorted(self.calls)]}


async def kept_stream(stream: Any, model: str, messages: list[dict], tools: list | None):
    """Hands each piece of a streamed reply on as it comes, and keeps the whole call once the stream ends. A stream
    the caller stops reading part-way is not kept (its reply is unfinished)."""
    reply = StreamedReply()
    async for part in stream:
        try:
            reply.add(part)
        except Exception:  # noqa: BLE001
            log.debug("reading a streamed piece failed", exc_info=True)
        yield part
    keep(model, messages, tools, reply.whole(), reply.usage)
