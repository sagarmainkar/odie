from types import SimpleNamespace

from odie.agent.callbacks import OdiePlugin
from odie.store.db import Store


def _tool(name, props, extra=False):
    schema = {"type": "object", "properties": {p: {"type": "string"} for p in props}}
    if extra:
        schema["additionalProperties"] = True
    return SimpleNamespace(name=name, _get_declaration=lambda: SimpleNamespace(parameters_json_schema=schema, parameters=None))


DRAFT = _tool("gmail_create_draft", ["to", "cc", "subject", "body", "reply_to_message_id", "reply_all"])


def _plugin(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return OdiePlugin(s)


async def test_a_value_glued_onto_its_field_name_is_put_back(tmp_path):
    p = _plugin(tmp_path)
    args = {"to": "ravi@example.com", "cc": "", "body": "Paid.", "subject NEFT Payment Dated 06 Oct 26 - Maintenance": ""}
    out = await p.before_tool_callback(tool=DRAFT, tool_args=args, tool_context=None)
    assert out is None  # the tool runs
    assert args["subject"] == "NEFT Payment Dated 06 Oct 26 - Maintenance" and "subject NEFT Payment Dated 06 Oct 26 - Maintenance" not in args


async def test_the_same_slip_on_another_field(tmp_path):
    p = _plugin(tmp_path)
    args = {"to ravi@example.com": "", "subject": "Hi", "body": "x"}
    assert await p.before_tool_callback(tool=DRAFT, tool_args=args, tool_context=None) is None
    assert args["to"] == "ravi@example.com"


async def test_an_unknown_field_gets_a_clear_message_instead_of_a_run(tmp_path):
    p = _plugin(tmp_path)
    args = {"recipient": "ravi@example.com", "subject": "Hi", "body": "x"}
    out = await p.before_tool_callback(tool=DRAFT, tool_args=args, tool_context=None)
    assert out and "recipient" in out["error"] and "to, cc, subject, body" in out["error"] and "exact" in out["error"]


async def test_a_field_already_filled_is_never_overwritten(tmp_path):
    p = _plugin(tmp_path)
    args = {"subject": "Real subject", "subject extra words": "", "body": "x", "to": "a@b.c"}
    out = await p.before_tool_callback(tool=DRAFT, tool_args=args, tool_context=None)
    assert args["subject"] == "Real subject" and out and "subject extra words" in out["error"]


async def test_tools_that_take_any_field_are_left_alone(tmp_path):
    p = _plugin(tmp_path)
    args = {"anything": 1}
    assert await p.before_tool_callback(tool=_tool("loose", ["a"], extra=True), tool_args=args, tool_context=None) is None
    no_schema = SimpleNamespace(name="x", _get_declaration=lambda: None)
    assert await p.before_tool_callback(tool=no_schema, tool_args={"q": 1}, tool_context=None) is None
