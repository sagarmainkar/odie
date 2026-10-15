"""Earlier turns go to the model exactly as sent until the chat passes its limit; then everything older than the last
five turns goes as words only (odie.agent.compaction), in rare cuts, so every provider's prompt cache is reused. Also
the request comparer (odie.prefix_check) these checks rely on."""
from __future__ import annotations

import json

from google.genai import types

from odie.agent.compaction import (DEFAULT_LIMIT, IMAGE_TEXT, KEEP_TURNS, Cuts, compact, compact_at, cut_points,
                                   is_users_message, size_of, words_only)
from odie.prefix_check import compare, pieces


def _user(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def _model(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


def _thinking_call(name: str, thought: str = "let me look that up") -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=thought, thought=True),
                                              types.Part(function_call=types.FunctionCall(id=name, name=name, args={}))])


def _result(name: str, text: str, **more) -> types.Content:
    fr = types.FunctionResponse(id=name, name=name, response={"result": text, **more})
    return types.Content(role="user", parts=[types.Part(function_response=fr)])


def _turn(n: int, size: int = 3000, thought: str = "let me look that up") -> list[types.Content]:
    """One turn: a question with Odie's note, thinking and a tool call, a big result, the answer."""
    return [_user(f"question {n}\n\n[context: now 09:{n % 60:02d} Mon 12 Oct]"), _thinking_call(f"search{n}", thought),
            _result(f"search{n}", "x" * size), _model(f"answer {n}")]


def _dumps(contents) -> list[str]:
    return [json.dumps(c.model_dump(mode="json", exclude_none=True), sort_keys=True) for c in contents]


def _no_tools_or_thinking(contents) -> bool:
    for c in contents:
        for p in c.parts:
            if p.thought or p.function_call is not None or p.function_response is not None:
                return False
    return True


def test_the_limit_is_the_models_limit_less_the_prompt_in_characters():
    assert compact_at(300_000) == 1_136_000     # DeepSeek or Claude with 1M context, less room for prompt and tools
    assert compact_at(52_500) == 146_000        # Gemma loaded with 70k context
    assert DEFAULT_LIMIT == 136_000             # a provider that can't say its size
    assert compact_at(3_072) == 3_072           # a 4k window: a quarter of its limit


def test_the_cut_follows_the_worked_example():
    contents = [_user("u" * 10), _result("a", "r" * 600), _model("m" * 50), _user("u" * 10), _result("b", "r" * 300),
                _model("m" * 50), _user("u" * 5)]
    assert cut_points(contents, limit=10_000, keep=1) == Cuts(0, 0)
    assert cut_points(contents, limit=1_000, keep=1) == Cuts(drop=0, cut=3)


def test_under_the_limit_history_goes_exactly_as_it_was():
    contents = [*_turn(1), *_turn(2), _user("question 3")]
    assert _dumps(compact(contents)) == _dumps(contents)


def test_past_the_limit_the_last_five_turns_stay_whole_and_the_rest_is_words():
    photo = types.Content(role="user", parts=[types.Part(text="what is this?\n\n[context: now 09:00 Mon 12 Oct]"),
                                              types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=b"a" * 100))])
    contents = [photo, _model("a cat")]
    for n in range(1, 12):
        contents += _turn(n)
    contents.append(_user("question 12"))
    before = _dumps(contents)
    out = compact(contents, limit=38_000)  # passed first at question 12 (~40.8k before it; ~37.7k before question 11)
    kept_from = contents.index(next(c for c in contents if c.parts[0].text and c.parts[0].text.startswith("question 7")))
    words = out[:len(out) - (len(contents) - kept_from)]
    assert _dumps(out[len(words):]) == before[kept_from:]                # turns 7-11 and the current one: as they were
    assert _no_tools_or_thinking(words)
    assert [c.role for c in words] == ["user", "model"] * 7               # the photo turn and turns 1-6, alternating
    assert words[0].parts[0].text == "what is this?" and words[0].parts[1].text == IMAGE_TEXT
    assert [p.text for p in words[2].parts] == ["question 1"] and [p.text for p in words[3].parts] == ["answer 1"]
    assert _dumps(contents) == before                                     # the session's copy: untouched


def test_words_only_keeps_what_was_said_and_nothing_else():
    assert words_only(_thinking_call("search")) is None
    said = types.Content(role="model", parts=[types.Part(text="found it", thought=True), types.Part(text="It's Friday.")])
    assert [p.text for p in words_only(said).parts] == ["It's Friday."]
    assert words_only(_result("search", "x" * 50)) is None
    asked = words_only(_user("When?\n\n[context: now 09:30 Mon 12 Oct]"))
    assert [p.text for p in asked.parts] == ["When?"]
    for c in (*_turn(1), said):
        assert size_of(words_only(c)) <= size_of(c)


def test_a_growing_chat_only_appends_between_rare_cuts():
    """Request after request of a growing chat (each turn's steps in order): every request starts with the one before,
    except at a few cuts, each at the start of a turn."""
    chat: list[types.Content] = []
    requests = []
    for n in range(60):
        turn = _turn(n)
        for step in (1, 3):  # the request with the question, then the one with the tool's result
            requests.append(compact([*chat, *turn[:step]], limit=40_000))
        chat += turn
    cuts = []
    for i, (before, now) in enumerate(zip(requests, requests[1:]), 1):
        a, b = _dumps(before), _dumps(now)
        if b[:len(a)] != a:
            cuts.append(i)
    assert 2 <= len(cuts) <= 8, cuts              # ~190k characters of tools and thinking against a 40k limit
    assert all(i % 2 == 0 for i in cuts)          # always the first request of a turn
    assert sum(size_of(c) for c in requests[-1]) < 40_000 + 4 * 3_200 * (KEEP_TURNS + 1)


def test_neighbours_of_one_role_are_joined_in_the_words():
    contents = [_user("plan my day"), _model("Looking at your calendar first."), _thinking_call("calendar"),
                _result("calendar", "x" * 4000), _model("You have two meetings."), *_turn(2), *_turn(3), _user("thanks")]
    out = compact(contents, limit=7_000, keep=2)  # passed at "thanks": the cut keeps turns 2 and 3 whole
    assert [c.role for c in out[:2]] == ["user", "model"]
    assert [p.text for p in out[1].parts] == ["Looking at your calendar first.", "You have two meetings."]


def test_when_the_words_alone_pass_the_limit_the_oldest_turns_go():
    contents = []
    for n in range(80):
        contents += [_user(f"question {n} " + "q" * 400), _model(f"answer {n} " + "a" * 600)]
    contents.append(_user("question 80"))
    out = compact(contents, limit=20_000)
    total = sum(size_of(c) for c in out)
    assert total <= 20_000
    assert out[-1].parts[0].text == "question 80" and out[-2].parts[0].text.startswith("answer 79")  # the newest stay
    assert not any(c.parts[0].text.startswith("question 0 ") for c in out)                            # the oldest went
    assert is_users_message(out[0])                                                                    # starts with a question


def test_the_chat_of_15_october_keeps_every_word():
    """Its shape (39 turns; per turn ~1.3k characters from the user, ~1.9k from Odie, ~10k of tools, ~11k of thinking),
    with made-up text: no cut under DeepSeek's 300k-token limit; past a smaller one, every turn's words stay."""
    contents = []
    for n in range(39):
        contents += [_user(f"message {n} " + "u" * 1300), _thinking_call(f"tool{n}", "t" * 11_000),
                     _result(f"tool{n}", "r" * 10_000), _model(f"reply {n} " + "o" * 1900)]
    contents.append(_user("message 39"))
    assert _dumps(compact(contents, limit=compact_at(300_000))) == _dumps(contents)
    out = compact(contents, limit=600_000)
    said = [p.text for c in out for p in c.parts if p.text and not p.thought]
    assert all(any(t.startswith(f"message {n} ") for t in said) for n in range(39))
    assert all(any(t.startswith(f"reply {n} ") for t in said) for n in range(39))
    assert _dumps(out[-(4 * KEEP_TURNS + 1):]) == _dumps(contents[-(4 * KEEP_TURNS + 1):])  # the last 5 turns whole


# ── odie.prefix_check ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_comparer_reads_both_request_shapes_and_finds_the_first_change():
    openai = {"tools": [{"function": {"name": "now"}}], "messages": [{"role": "system", "content": "You are Odie."},
                                                                      {"role": "user", "content": "hi"}]}
    grown = {**openai, "messages": [*openai["messages"], {"role": "assistant", "content": "hello"}]}
    assert [label for label, _ in pieces(openai)] == ["tools", "message 0 (system)", "message 1 (user)"]
    step = compare("2", pieces(openai), pieces(grown))
    assert step.appended and step.reusable == sum(len(t) for _, t in pieces(openai))
    edited = {**grown, "messages": [openai["messages"][0], {"role": "user", "content": "hi there"}, grown["messages"][2]]}
    step = compare("3", pieces(grown), pieces(edited))
    assert not step.appended and step.where == "message 1 (user)"
    claude = {"tools": [], "system": [{"type": "text", "text": "You are Odie.", "cache_control": {"type": "ephemeral"}}],
              "messages": [{"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]}]}
    hello = {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}
    moved = {**claude, "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]},
                                    {"role": "assistant", "content": [hello]}]}
    assert compare("", pieces(claude), pieces(moved)).appended  # a moved cache mark isn't a change


def test_the_comparer_reports_a_folder(tmp_path):
    from odie.prefix_check import report
    a = {"tools": [], "messages": [{"role": "user", "content": "hi"}]}
    b = {"tools": [], "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}
    c = {"tools": [{"x": 1}], "messages": b["messages"]}
    for name, body in (("1", a), ("2", b), ("3", c)):
        (tmp_path / f"{name}.json").write_text(json.dumps(body))
    text = report(tmp_path)
    assert "APPEND-ONLY" in text and "CHANGED at tools" in text and "1 of 2 requests changed something earlier" in text
