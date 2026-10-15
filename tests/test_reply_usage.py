"""Each reply carries the token counts of the model call that made it (input, how much of it came from the provider's
prompt cache, output), as it streams in and again from history, so the chat can show under the reply whether caching
worked for it. A fake or an old event without counts carries nothing."""
from google.adk.events import Event
from google.genai import types

from odie.app.runner import event_to_sse, events_to_history


def _reply(text: str, counts: tuple[int, int, int] | None = None, partial: bool = False) -> Event:
    meta = None
    if counts:
        meta = types.GenerateContentResponseUsageMetadata(prompt_token_count=counts[0], cached_content_token_count=counts[1],
                                                           candidates_token_count=counts[2])
    return Event(author="odie", partial=partial, content=types.Content(role="model", parts=[types.Part(text=text)]), usage_metadata=meta)


def test_the_streamed_reply_carries_its_counts():
    items = event_to_sse(_reply("Hi.", counts=(9800, 8900, 250)))
    assert items[0]["type"] == "text" and items[0]["usage"] == {"input": 9800, "cached": 8900, "output": 250}
    assert "usage" not in event_to_sse(_reply("Hi.", counts=None))[0]                      # no counts: nothing to show
    assert "usage" not in event_to_sse(_reply("Hi", counts=(9800, 8900, 250), partial=True))[0]  # tokens as they stream: not yet


def test_history_carries_each_replys_counts():
    events = [Event(author="user", content=types.Content(role="user", parts=[types.Part(text="hi")])),
              _reply("Hi.", counts=(9800, 8900, 250)),
              Event(author="user", content=types.Content(role="user", parts=[types.Part(text="and?")])),
              _reply("More.", counts=None)]
    odie = [h for h in events_to_history(events) if h["role"] == "odie"]
    assert odie[0]["usage"] == {"input": 9800, "cached": 8900, "output": 250}
    assert "usage" not in odie[1]
