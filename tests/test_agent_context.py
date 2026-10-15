"""session_id_of and parts_of: the two ADK readers, on real ADK objects and on the gaps they must survive."""
from types import SimpleNamespace

from google.adk.events import Event
from google.genai import types

from odie.agent.context import parts_of, session_id_of


def test_session_id_of_reads_the_session_id():
    ctx = SimpleNamespace(session=SimpleNamespace(id="abc123"))
    assert session_id_of(ctx) == "abc123"


def test_session_id_of_is_none_without_a_session():
    assert session_id_of(None) is None
    assert session_id_of(SimpleNamespace()) is None
    assert session_id_of(SimpleNamespace(session=None)) is None
    assert session_id_of(SimpleNamespace(session=SimpleNamespace())) is None


def test_parts_of_a_real_adk_event():
    call = types.Part(function_call=types.FunctionCall(name="web_search", args={"query": "rain"}))
    ev = Event(author="odie", content=types.Content(role="model", parts=[call]))
    got = parts_of(ev)
    assert len(got) == 1 and got[0].function_call.name == "web_search"


def test_parts_of_is_empty_when_there_is_nothing():
    assert parts_of(None) == []
    assert parts_of(Event(author="odie")) == []
    assert parts_of(Event(author="odie", content=types.Content(role="model"))) == []
    assert parts_of(Event(author="odie", content=types.Content(role="model", parts=[]))) == []
