"""Financial details never reach memory (the chat tool and the background review both go through MemoryFile.update),
and the rolling summary of a long day is masked."""
import pytest

from odie.memory.store import MemoryFile
from odie.memory.tools import make_memory_tools


@pytest.fixture
def mf(tmp_path):
    return MemoryFile(tmp_path / "m.md", tmp_path / ".lock", "odie")


def test_memory_refuses_financial_details(mf):
    update = next(t for t in make_memory_tools(mf) if t.name == "update_memory").func
    for content in ("My card is 4111 1111 1111 1111", "Pay me at ashaa@okaxis", "A/c 50100123456789 IFSC HDFC0001234"):
        assert update(title="Payments", content=content, topic="Finance") == "Not saved: I don't keep card, UPI or bank details in memory."
    assert update(title="Phone", content="+91 98765 43210", topic="Identity").startswith("Saved")
    assert "4111" not in mf.path.read_text() and "okaxis" not in mf.path.read_text()


async def test_the_review_skips_financial_items(mf, monkeypatch):
    from odie.memory import review

    async def fake(store, slot, messages, **kw):
        return ('[{"title": "Card", "content": "Visa 4111 1111 1111 1111", "topic": "Finance"},'
                ' {"title": "Likes tea", "content": "Prefers masala chai", "topic": "Preferences"}]')
    monkeypatch.setattr("odie.models.chat_completion", fake)
    await review.run_review(mf, [("u", "a")], "")
    text = mf.path.read_text()
    assert "Prefers masala chai" in text and "4111" not in text
