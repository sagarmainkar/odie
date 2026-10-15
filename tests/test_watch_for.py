"""Watch for: chat Odie saves a standing instruction when the user asks; the review never writes one; at most 30."""
import json

import pytest

from odie.memory import review
from odie.memory.store import MemoryFile


def test_the_review_never_writes_watch_for():
    items = review.parse_items(json.dumps([{"topic": "Watch for", "title": "Forward invoices", "content": "forward to x"},
                                           {"topic": "Finance", "title": "Bank", "content": "Uses HDFC"}]))
    assert [i["topic"] for i in items] == ["Finance"]
    assert "Watch for" in review.SYSTEM


def test_the_rule_says_when_to_save_one():
    from odie.agent.prompt import RULES
    rule = next(r for r in RULES if r.id == "watchfor")
    assert 'topic="Watch for"' in rule.text and "never" in rule.text.lower()


def test_at_most_30(tmp_path):
    from odie.memory.tools import make_memory_tools
    m = MemoryFile(tmp_path / "m.md", tmp_path / "m.lock", "odie")
    tools = {t.name: t for t in make_memory_tools(m)}
    upd = tools["update_memory"].func
    for i in range(30):
        assert "Saved" in upd(title=f"Thing {i}", content="When: x. Do: y.", topic="Watch for") or True
    out = upd(title="One more", content="When: x.", topic="Watch for")
    assert "30" in out and m.load().find("One more") is None
    assert m.load().find("Thing 3") is not None and "30" not in upd(title="Thing 3", content="When: changed.", topic="Watch for")


def test_a_standing_instruction_can_be_removed(tmp_path):
    from odie.memory.tools import make_memory_tools
    m = MemoryFile(tmp_path / "m.md", tmp_path / "m.lock", "odie")
    tools = {t.name: t for t in make_memory_tools(m)}
    tools["update_memory"].func(title="Passport email", content="When: it comes. Do: tell me.", topic="Watch for")
    out = tools["forget_memory"].func(title="Passport email")
    assert "Forgot" in out and m.load().find("Passport email") is None
    assert "Passport email" in m.history_path.read_text()  # kept in the history, not lost
    assert "No memory" in tools["forget_memory"].func(title="Never saved")
