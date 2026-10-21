"""Each history line says which turn it came from: the invocation id of the event behind it. A model that talks
before every tool call ("Let me check…") leaves a turn as several Odie lines; an app can fold the lines of one turn
into the one answer, as the live stream already shows them, and still tell a message Odie posted on its own (a
reminder, a job's note) from them, since a posted message is a turn of its own."""
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
