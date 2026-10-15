"""What earlier turns look like in a request to the model: exactly as they were sent, until the chat passes its limit;
then everything older than the last few turns goes as words only (2026-10-15).

Why exactly as sent: every provider reuses the start of the last prompt it read (LM Studio's and llama.cpp's KV cache,
Ollama and OpenAI-style services, Claude's prompt cache), but only up to the first character that changed. So history
goes unchanged, request after request, and each request starts with the one before.

Why words only past the limit: a long chat is mostly tool traffic and thinking, not words. A DeepSeek chat of 15 Oct
held ~31k tokens of the user's and Odie's words next to ~101k of tool calls and results and ~110k of thinking. Before,
Odie summarised such a chat into one paragraph and started over; now it keeps every word and drops the rest.

The rule. The limit is the model's (odie.models.history_limit_for, in tokens; compact_at turns it into characters).
When the history before a user's message passes it, the cut moves to KEEP_TURNS turns before that message (fewer
when those turns alone would fill more than half the limit, so the chat has room to grow before the next cut):
  - from the cut on, everything goes as it was: the last KEEP_TURNS turns and the current one, thinking and tools too;
  - before the cut, words only (words_only): the user's messages without Odie's notes, Odie's replies as written; its
    thinking, tool calls and tool results are left out, photos become a line of text, empty messages go;
  - if the words still don't fit, the oldest turns are left out entirely until what's left is half the limit (the
    fallback; no summary).
Each cut is decided at a user's message from the messages before it only, so every later request finds the same cuts:
requests grow append-only until the next cut, and the cache breaks only then. No model is called; it's milliseconds.

Worked example, limit 100k characters, KEEP_TURNS 5:
  turns 1-30 hold 95k (tool results and thinking included)  -> no cut: every request adds to the one before
  turn 31 starts with 104k before it                         -> cut at turn 26: turns 1-25 as words (~12k), turns
                                                                26-30 and 31 whole. This request changes at turn 1
  turns 31-60 add 80k: 92k before turn 61                    -> the cut stays at turn 26: append-only again
  turn 62 starts with 101k before it                         -> cut at turn 57, and so on
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import accumulate
from typing import Any

IMAGE_TEXT = "[image omitted from earlier in the conversation; ask the user to attach it again if needed]"
TRAILER = "\n\n[context: "

KEEP_TURNS = 5             # turns before the current one that stay whole when the cut moves (at most)
CHARS_PER_TOKEN = 4        # a rough rate for English text and JSON
PROMPT_ROOM = 16_000       # tokens of every request that aren't history: the system prompt and tools (~14.5k, 15 Oct)
ROOM_AFTER_CUT = 0.5       # after a cut the history is at most this share of the limit, so cuts stay rare
IMAGE_CHARS = 6_000        # what a photo counts as (~1.5k tokens), whatever its size in bytes


def compact_at(limit_tokens: int) -> int:
    """How many characters of history a request may carry, from the chat's limit in tokens (odie.models.
    history_limit_for): the limit less PROMPT_ROOM for the system prompt and tools, so the whole request is at the limit
    when the cut moves (the chat's ring shows the same count). At least a quarter of the limit, for tiny windows.
      DeepSeek or Claude, 1M context -> 300k tokens   -> (300,000 - 16,000) x 4 = 1,136,000 characters
      Gemma in LM Studio, 70k context -> 52.5k tokens -> (52,500 - 16,000) x 4 =   146,000 characters
      a provider that can't say       -> 50k tokens   -> (50,000 - 16,000) x 4 =   136,000 characters
      a 4k window                     -> 3,072 tokens -> a quarter, 768 tokens  =     3,072 characters"""
    history_tokens = max(limit_tokens - PROMPT_ROOM, limit_tokens // 4)
    return int(history_tokens * CHARS_PER_TOKEN)


DEFAULT_LIMIT = compact_at(50_000)  # odie.models.HISTORY_LIMIT_UNKNOWN: for a request outside a chat turn


def is_users_message(content: Any) -> bool:
    """A message the user wrote: role=user with text and no tool result (a tool's result comes back as a user
    message too, without text)."""
    parts = getattr(content, "parts", None) or []
    if getattr(content, "role", None) != "user":
        return False
    has_text = any(getattr(p, "text", None) for p in parts)
    has_tool_result = any(getattr(p, "function_response", None) for p in parts)
    return has_text and not has_tool_result


def turn_start(contents: list[Any]) -> int:
    """Where the current turn starts: the index of the user's last message (0 when there's none). Everything from
    there on is this turn: the question, the model's tool calls and their results.
      [user "hi", model "hello", user "time?", model call now(), user now() -> "18:52"]  ->  2"""
    start = 0
    for i, c in enumerate(contents):
        if is_users_message(c):
            start = i
    return start


def size_of(content: Any) -> int:
    """Roughly how many characters a message puts in front of the model: its text, its tool calls and results as
    JSON, IMAGE_CHARS per photo. None (a message words_only left empty) is 0."""
    n = 0
    for p in getattr(content, "parts", None) or []:
        if p.text:
            n += len(p.text)
        if p.function_call is not None:
            n += len(json.dumps(p.function_call.args or {}, default=str)) + 40
        if p.function_response is not None:
            n += len(json.dumps(p.function_response.response or {}, default=str)) + 40
        if p.inline_data is not None:
            n += IMAGE_CHARS
    return n


def _without_trailer(text: str) -> str:
    """A user's message without Odie's additions after their words: prefetched blocks and the [context: …] note.
      "Who rang?\\n\\n[from your notes…]…\\n\\n[context: now 09:30 Tue 6 Oct]" -> "Who rang?" """
    from odie.agent.prefetch import strip_blocks
    text = strip_blocks(text)
    i = text.rfind(TRAILER)
    return text[:i] if i >= 0 else text


def words_only(content: Any) -> Any | None:
    """A copy of one earlier message with only its words: the user's text without Odie's additions, the model's reply
    text; thinking, tool calls and tool results left out; a photo as a line of text. None when nothing is left.
      model [thought "let me look", call search()]       -> None
      model [thought "found it", text "It's on Friday."]  -> model [text "It's on Friday."]
      user  [text "When?\\n\\n[context: now 09:30 …]"]    -> user [text "When?"]
    The session's copy is untouched."""
    users = is_users_message(content)
    parts = []
    for p in getattr(content, "parts", None) or []:
        if getattr(p, "thought", False) or p.function_call is not None or p.function_response is not None:
            continue
        if p.inline_data is not None:
            parts.append(p.model_copy(update={"inline_data": None, "text": IMAGE_TEXT, "thought_signature": None}))
            continue
        if not p.text:
            continue
        text = p.text
        if users:
            text = _without_trailer(text)
        parts.append(p.model_copy(update={"text": text, "thought_signature": None}))
    if not parts:
        return None
    return content.model_copy(update={"parts": parts})


@dataclass(frozen=True)
class Cuts:
    """Where a request's history is shortened: messages before `drop` are left out (the fallback, usually 0); from
    `drop` to `cut` they go as words only; from `cut` on, as they were."""
    drop: int = 0
    cut: int = 0


def cut_points(contents: list[Any], limit: int, keep: int = KEEP_TURNS) -> Cuts:
    """Where to shorten this history (see the module's notes). Walks the user's messages in order; at each, measures
    what the request would hold before it with the cuts so far. Over the limit: the cut moves `keep` turns back, or
    fewer when those turns take more than half the limit (_fits_whole); and if the words still don't fit, the oldest
    turns are dropped (_oldest_kept).
    Worked example, limit 1,000, keep 1: [user 10, tool result ~640, model 50, user 10, tool result ~340, model 50,
    user 5]
      at the 2nd user message: ~700 before it, under 1,000                            -> no cut
      at the 3rd user message: ~1,100 before it, over 1,000; one turn back is the 2nd -> cut there (index 3): the 1st
      turn goes as words (60); the 2nd turn (~400, under half the limit) and the current one whole"""
    raw = list(accumulate((size_of(c) for c in contents), initial=0))
    words = list(accumulate((size_of(words_only(c)) for c in contents), initial=0))
    users: list[int] = []
    drop = cut = 0
    for i, c in enumerate(contents):
        if not is_users_message(c):
            continue
        users.append(i)
        before = (words[cut] - words[drop]) + (raw[i] - raw[cut])
        if before <= limit:
            continue
        turns_before = len(users) - 1
        if turns_before >= keep:
            cut = max(cut, users[-1 - keep])
        cut = _fits_whole(users, cut, i, raw, int(limit * ROOM_AFTER_CUT))
        whole = raw[i] - raw[cut]
        if (words[cut] - words[drop]) + whole > limit:
            drop = _oldest_kept(users, drop, cut, words, _room_for_words(limit, whole))
    return Cuts(drop, cut)


def _fits_whole(users: list[int], cut: int, now: int, raw: list[int], room: int) -> int:
    """Where the turns that go whole start: at `cut`, or at a later user message when the turns from `cut` up to now
    take more than `room` characters; at `now` (only the current turn whole) when even the last turn does.
      turns of 3,000 each from the cut, room 4,500 -> start at the last turn before now (3,000 fits, 6,000 doesn't)"""
    for start in users:
        if cut <= start <= now and raw[now] - raw[start] <= room:
            return start
    return now


def _room_for_words(limit: int, whole: int) -> int:
    """How many characters of words the fallback keeps, next to `whole` characters of turns that go as they were: up
    to half the limit in all, so the chat has room to grow before the next cut; or what still fits under the limit
    when the whole turns alone take more than half.
      limit 1,000, whole 300 -> 200 (500 in all); whole 700 -> 300 (1,000 in all); whole 1,200 -> 0"""
    target = int(limit * ROOM_AFTER_CUT)
    if whole < target:
        return target - whole
    return max(0, limit - whole)


def _oldest_kept(users: list[int], drop: int, cut: int, words: list[int], room: int) -> int:
    """The fallback's new start: the earliest user message at or after `drop` from which the words up to the cut fit
    in `room` characters; the cut itself (no words kept) when none does.
      words per turn 400, 300, 200 before the cut, room 600 -> start at the 2nd turn (300 + 200 = 500 fits)"""
    for start in users:
        if drop <= start <= cut and words[cut] - words[start] <= room:
            return start
    return cut


def compact(contents: list[Any], limit: int = DEFAULT_LIMIT, keep: int = KEEP_TURNS) -> list[Any]:
    """The request's history with the cuts applied (copies; the session keeps its own). Under the limit it is the
    history exactly as it was. Neighbouring messages of one role in the words-only part are joined into one, so a
    provider that wants turns to alternate gets them that way; the turns after the cut are never changed, except that
    the words of a last unanswered message join the first of them."""
    where = cut_points(contents, limit, keep)
    if where.drop == 0 and where.cut == 0:
        return list(contents)
    older = [w for w in (words_only(c) for c in contents[where.drop:where.cut]) if w is not None]
    joined = _joined(older)
    kept = list(contents[where.cut:])
    if joined and kept and joined[-1].role == kept[0].role:
        last = joined.pop()
        kept[0] = kept[0].model_copy(update={"parts": [*last.parts, *kept[0].parts]})
    return joined + kept


def _joined(contents: list[Any]) -> list[Any]:
    """Neighbouring messages of one role as one message.
      [user "a", model "b", model "c", user "d"] -> [user "a", model "b" + "c", user "d"]"""
    out: list[Any] = []
    for c in contents:
        if out and out[-1].role == c.role:
            out[-1] = out[-1].model_copy(update={"parts": [*out[-1].parts, *c.parts]})
        else:
            out.append(c)
    return out
