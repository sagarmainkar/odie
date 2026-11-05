"""Each history line says which turn it came from: the invocation id of the event behind it. A model that talks
before every tool call ("Let me check…") leaves a turn as several Odie lines; an app can fold the lines of one turn
into the one answer, as the live stream already shows them, and still tell a message Odie posted on its own (a
reminder, a job's note) from them, since a posted message is a turn of its own."""
from datetime import UTC, datetime

from google.adk.events import Event
from google.genai import types

from odie.app.runner import events_to_history


def _event(author: str, text: str, inv: str) -> Event:
    role = "model" if author == "odie" else "user"
    return Event(author=author, invocation_id=inv, content=types.Content(role=role, parts=[types.Part(text=text)]))


def test_history_lines_carry_their_turn():
    events = [_event("user", "where is aerospace offered?", "e-1"),
              _event("odie", "Let me check.", "e-1"),
              _event("odie", "Three colleges offer it.", "e-1"),
              _event("odie", "Time to check on this: the HN appeal.", "odie-ab12"),  # posted on its own: a turn of its own
              _event("user", "and the fees?", "e-2"),
              _event("odie", "About two lakh a year.", "e-2")]
    turns = [(h["role"], h["inv"]) for h in events_to_history(events)]
    assert turns == [("user", "e-1"), ("odie", "e-1"), ("odie", "e-1"), ("odie", "odie-ab12"), ("user", "e-2"), ("odie", "e-2")]


def test_a_line_from_an_event_without_a_turn_says_nothing():
    plain = Event(author="odie", content=types.Content(role="model", parts=[types.Part(text="Hi.")]))
    assert "inv" not in events_to_history([plain])[0]


# ---- steps: each Odie line carries the tool calls it made ----

def _calls(author: str, inv: str, *calls: tuple[str, str, dict]) -> Event:
    parts = [types.Part(function_call=types.FunctionCall(name=name, id=call_id, args=args)) for name, call_id, args in calls]
    return Event(author=author, invocation_id=inv, content=types.Content(role="model", parts=parts))


def _answers(inv: str, *answers: tuple[str, str, dict]) -> Event:
    parts = [types.Part(function_response=types.FunctionResponse(name=name, id=call_id, response=response))
             for name, call_id, response in answers]
    return Event(author="odie", invocation_id=inv, content=types.Content(role="user", parts=parts))


WAITING_ANSWER = {"error": "This tool call requires confirmation, please approve or reject."}
REJECTED_ANSWER = {"error": "This tool call is rejected."}


def test_history_steps_pair_call_and_response_by_id():
    # Two calls in one event; the answers come back in the other order, in one event. Each call keeps its own.
    events = [_event("user", "look both up", "e-1"),
              _calls("odie", "e-1", ("web_search", "c1", {"query": "cats"}), ("web_fetch", "c2", {"url": "http://example.com"})),
              _answers("e-1", ("web_fetch", "c2", {"result": "page"}), ("web_search", "c1", {"result": "3 hits"})),
              _event("odie", "Done.", "e-1")]
    lines = events_to_history(events)
    steps = lines[1]["steps"]
    assert [(s["name"], s["id"], s["result"], s["state"]) for s in steps] == [
        ("web_search", "c1", "3 hits", "done"), ("web_fetch", "c2", "page", "done")]
    assert steps[0]["args"] == {"query": "cats"}
    assert steps[0]["allowed"] is None


def _timed(event: Event, ts: float) -> Event:
    event.timestamp = ts
    return event


def _confirmation_request(inv: str, request_id: str, call_id: str, tool: str, args: dict) -> Event:
    """ADK's own question for a gated call: a model event with a call to adk_request_confirmation that wraps it."""
    original = {"id": call_id, "name": tool, "args": args}
    return _calls("odie", inv, ("adk_request_confirmation", request_id, {"originalFunctionCall": original, "toolConfirmation": {"hint": ""}}))


def _confirmation(inv: str, request_id: str, confirmed: bool) -> Event:
    """The tap, as ADK stores it: a user event answering the confirmation call."""
    answer = types.FunctionResponse(name="adk_request_confirmation", id=request_id, response={"confirmed": confirmed})
    return Event(author="user", invocation_id=inv, content=types.Content(role="user", parts=[types.Part(function_response=answer)]))


def _gated_shell_turn(start: float, result: dict) -> list[Event]:
    """A gated `ls` in a resumable app, as ADK really writes it: the call, the "requires confirmation" answer, the
    confirmation call (and the pause); a minute later the tap, the real result, and the reply."""
    return [_timed(_event("user", "list files", "e-1"), start),
            _timed(_calls("odie", "e-1", ("run_shell", "c1", {"command": "ls"})), start + 1),
            _timed(_answers("e-1", ("run_shell", "c1", WAITING_ANSWER)), start + 1),
            _timed(_confirmation_request("e-1", "r1", "c1", "run_shell", {"command": "ls"}), start + 2),
            _timed(_confirmation("e-1", "r1", True), start + 60),
            _timed(_answers("e-1", ("run_shell", "c1", result)), start + 61),
            _timed(_event("odie", "One file.", "e-1"), start + 62)]


def test_the_reply_after_a_tap_sits_below_its_card(tmp_path):
    from odie.app.runner import merge_approvals

    store = _store(tmp_path)
    start = datetime(2026, 11, 5, 10, 0, tzinfo=UTC).timestamp()
    row = store.create_approval("chat-1", "e-1", "r1", "run_shell", {"command": "ls"}, "Run", {}, [], call_id="c1")
    store.execute("update approvals set created_at=? where id=?", ("2026-11-05T10:00:02.500Z", row))  # with the question
    lines = events_to_history(_gated_shell_turn(start, {"result": "a.txt"}))
    items = merge_approvals(lines, store.approvals_in_sessions(["chat-1"]))
    assert [(i["role"], i["text"]) for i in items] == [("user", "list files"), ("odie", ""), ("approval", ""), ("odie", "One file.")]
    call_line, reply = items[1], items[3]
    assert [(s["id"], s["result"], s["state"]) for s in call_line["steps"]] == [("c1", "a.txt", "done")]  # on the call's line
    assert call_line["tools"] == ["run_shell"]  # gated tools are no longer hidden
    assert reply["steps"] == [] and reply["tools"] == []
    assert reply["ts"] == start + 62  # the reply keeps its own time


def test_history_step_states():
    events = [_calls("odie", "e-1", ("a", "c1", {}), ("b", "c2", {}), ("c", "c3", {}), ("d", "c4", {}), ("e", "c5", {})),
              _answers("e-1", ("a", "c1", WAITING_ANSWER), ("b", "c2", REJECTED_ANSWER),
                       ("c", "c3", {"error": "disk full"}), ("d", "c4", {"result": "ok"})),  # c5 has no answer yet
              _event("odie", "ok", "e-1")]
    steps = events_to_history(events)[0]["steps"]
    assert [(s["id"], s["state"]) for s in steps] == [("c1", "wait"), ("c2", "no"), ("c3", "done"), ("c4", "done"), ("c5", "wait")]
    assert steps[1]["result"] == "" and steps[1]["allowed"] == {"by": "no"}
    assert steps[2]["result"] == "Error: disk full"
    assert steps[4]["result"] == ""


def test_history_hides_only_the_confirmation_request():
    events = [_calls("odie", "e-1", ("run_shell", "c1", {"command": "ls"}), ("adk_request_confirmation", "q1", {})),
              _answers("e-1", ("adk_request_confirmation", "q1", {"confirmed": True})),
              _event("odie", "ok", "e-1")]
    line = events_to_history(events)[0]
    assert [s["name"] for s in line["steps"]] == ["run_shell"]
    assert line["tools"] == ["run_shell"]


def test_history_tools_names_unchanged():
    events = [_event("user", "go", "e-1"),
              _calls("odie", "e-1", ("web_search", "c1", {})),
              _answers("e-1", ("web_search", "c1", {"result": "x"})),
              _calls("odie", "e-1", ("web_fetch", "c2", {})),
              _answers("e-1", ("web_fetch", "c2", {"result": "y"})),
              _event("odie", "Here.", "e-1")]
    lines = events_to_history(events)
    assert lines[0]["tools"] == [] and "steps" not in lines[0]  # a user line has no steps
    assert lines[1]["tools"] == ["web_search", "web_fetch"]
    assert [s["name"] for s in lines[1]["steps"]] == ["web_search", "web_fetch"]


def test_history_steps_are_capped():
    events = [_calls("odie", "e-1", ("web_fetch", "c1", {"url": "u" * 900})),
              _answers("e-1", ("web_fetch", "c1", {"result": "x" * 10_000})),
              _event("odie", "ok", "e-1")]
    step = events_to_history(events)[0]["steps"][0]
    assert step["result"] == "x" * 3000 + "… (7000 more characters)"
    assert step["args"]["url"] == "u" * 500 + "…"


def test_history_a_shell_that_ran_shows_pass_without_a_row():
    events = [_calls("odie", "e-1", ("run_shell", "c1", {"command": "ls"})),
              _answers("e-1", ("run_shell", "c1", {"result": "a.txt"})),
              _event("odie", "ok", "e-1")]
    assert events_to_history(events)[0]["steps"][0]["allowed"] == {"by": "pass"}


def _store(tmp_path):
    from odie.store.db import Store

    store = Store(tmp_path / "a.db")
    store.init_schema()
    return store


def test_history_fills_allowed_from_the_store(tmp_path):
    from odie.app.runner import steps_with_allowed

    store = _store(tmp_path)
    yes = store.create_approval("chat-1", "e-1", "r1", "gmail_trash", {"message_id": "m1"}, "Trash", {}, [], call_id="c1")
    no = store.create_approval("chat-1", "e-1", "r2", "gmail_trash", {"message_id": "m2"}, "Trash", {}, [], call_id="c2")
    store.create_approval("chat-1", "e-1", "r3", "gmail_trash", {"message_id": "m3"}, "Trash", {}, [], call_id="c3")
    store.decide_approval(yes, True)
    store.decide_approval(no, False)
    events = [_calls("odie", "e-1", ("gmail_trash", "c1", {"message_id": "m1"}), ("gmail_trash", "c2", {"message_id": "m2"}),
                     ("gmail_trash", "c3", {"message_id": "m3"}), ("web_search", "c4", {})),
              _answers("e-1", ("gmail_trash", "c1", {"result": "trashed"}), ("gmail_trash", "c2", REJECTED_ANSWER),
                       ("gmail_trash", "c3", WAITING_ANSWER), ("web_search", "c4", {"result": "x"})),
              _event("odie", "ok", "e-1")]
    lines = steps_with_allowed(store, "chat-1", events_to_history(events))
    c1, c2, c3, c4 = lines[0]["steps"]
    assert c1["allowed"] == {"by": "you", "at": store.get_approval(yes)["decided_at"]}
    assert c2["allowed"] == {"by": "no", "at": store.get_approval(no)["decided_at"]}
    assert c3["state"] == "wait" and c3["allowed"] is None  # undecided: no pill
    assert c4["allowed"] is None


def test_a_decided_row_gives_no_pill_to_a_step_still_waiting(tmp_path):
    from odie.app.runner import steps_with_allowed

    store = _store(tmp_path)
    row = store.create_approval("chat-1", "e-1", "r1", "run_shell", {"command": "ls"}, "Run", {}, [], call_id="c1")
    store.decide_approval(row, True)  # tapped, but the real result has not landed yet
    events = [_calls("odie", "e-1", ("run_shell", "c1", {"command": "ls"})),
              _answers("e-1", ("run_shell", "c1", WAITING_ANSWER)),
              _event("odie", "waiting", "e-1")]
    step = steps_with_allowed(store, "chat-1", events_to_history(events))[0]["steps"][0]
    assert step["state"] == "wait" and step["allowed"] is None


def test_an_old_approval_matches_its_step_with_empty_or_long_arguments(tmp_path):
    # Old rows (no call_id) keep the full arguments; the step keeps capped ones. A None value or a value over 500
    # characters must still match, so a shell command the person approved is not shown as a pass.
    from odie.app.runner import steps_with_allowed

    store = _store(tmp_path)
    none_args = {"command": "ls", "cwd": None}
    long_args = {"command": "ls", "cwd": "d" * 600}
    for number, args in enumerate([none_args, long_args], start=1):
        row = store.create_approval("chat-1", f"e-{number}", f"r{number}", "run_shell", args, "Run", {}, [])
        store.decide_approval(row, True)
    events = [_calls("odie", "e-1", ("run_shell", "c1", none_args)),
              _answers("e-1", ("run_shell", "c1", {"result": "a.txt"})),
              _event("odie", "one", "e-1"),
              _calls("odie", "e-2", ("run_shell", "c2", long_args)),
              _answers("e-2", ("run_shell", "c2", {"result": "a.txt"})),
              _event("odie", "two", "e-2")]
    lines = [h for h in steps_with_allowed(store, "chat-1", events_to_history(events)) if h["role"] == "odie"]
    assert [h["steps"][0]["allowed"]["by"] for h in lines] == ["you", "you"]
