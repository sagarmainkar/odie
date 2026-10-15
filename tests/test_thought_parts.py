"""Through litellm a model's reasoning arrives as thought parts with text (DeepSeek's and Gemma's reasoning, Claude's
summaries; the old OpenAI adapter made none). They are the model's own notes: never shown as the reply, never in the
history, so they can't be read back as something Odie said."""
from google.adk.events import Event
from google.genai import types

from odie.app.runner import event_to_sse, events_to_history


def _odie_said(*parts: types.Part, partial: bool = False) -> Event:
    return Event(author="odie", content=types.Content(role="model", parts=list(parts)), partial=partial)


def test_the_chat_stream_leaves_thoughts_out():
    ev = _odie_said(types.Part(text="Let me think.", thought=True, thought_signature=b"sig"), types.Part(text="Hi."))
    assert [i["text"] for i in event_to_sse(ev) if i["type"] in ("text", "token")] == ["Hi."]
    streamed = _odie_said(types.Part(text="Let me", thought=True), partial=True)
    assert event_to_sse(streamed) == []


def test_the_history_leaves_thoughts_out():
    events = [Event(author="user", content=types.Content(role="user", parts=[types.Part(text="hi")])),
              _odie_said(types.Part(text="Let me think.", thought=True), types.Part(text="Hi."))]
    history = events_to_history(events)
    assert [h["text"] for h in history if h["role"] == "odie"] == ["Hi."]
