"""A background turn may let named tools through without the user's tap (the watch's calendar_create_event): the
turn's agent gets unlocked copies; the chat's tool objects keep asking."""
from types import SimpleNamespace

from google.adk.tools.base_toolset import BaseToolset

from odie.agent.free import FreedToolset, free_tools, unlocked


class Tools(BaseToolset):
    def __init__(self, tools):
        super().__init__()
        self.tools = tools

    async def get_tools(self, readonly_context=None):
        return list(self.tools)

    async def close(self):
        pass


def test_an_unlocked_tool_is_a_copy_that_does_not_ask():
    original = SimpleNamespace(name="calendar_create_event", _require_confirmation=True)
    freed = unlocked(original)
    assert freed._require_confirmation is False and original._require_confirmation is True
    assert freed.name == "calendar_create_event"


async def test_free_tools_unlocks_only_the_named_ones_inside_toolsets_and_beside_them():
    create = SimpleNamespace(name="calendar_create_event", _require_confirmation=True)
    send = SimpleNamespace(name="gmail_send_draft", _require_confirmation=True)
    search = SimpleNamespace(name="web_search", _require_confirmation=False)
    plain_create = SimpleNamespace(name="calendar_create_event", _require_confirmation=True)
    out = free_tools([search, Tools([create, send]), plain_create], frozenset({"calendar_create_event"}))
    assert out[0] is search
    assert isinstance(out[1], FreedToolset)
    got = await out[1].get_tools()
    assert [(t.name, t._require_confirmation) for t in got] == [("calendar_create_event", False), ("gmail_send_draft", True)]
    assert create._require_confirmation is True  # the chat's own stays as it was
    assert out[2] is not plain_create and out[2]._require_confirmation is False
    # nothing freed: the same list, untouched
    same = free_tools([search, create], frozenset())
    assert same == [search, create]
