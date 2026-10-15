from pathlib import Path

from odie.memory.index import build_index, render_prefetch
from odie.memory.review import parse_items
from odie.memory.search import prefetch_hits, search
from odie.memory.store import MemoryFile, parse, template

SAMPLE = """---
title: odie — long-term memory
---

# odie — long-term memory

## Identity

### Flight Seat Preference (2026-09-28)

Asha prefers aisle seats during flights.

### Asha (2026-09-29)

Full-stack engineer, founder. Lives in Pune, IST.

## Projects

Intro line for projects.

### Odie (2026-10-01)

Personal assistant on the home server.
```
## not a topic
```
"""


def test_parse_topics_entries_and_fences():
    doc = parse(SAMPLE)
    assert [t.name for t in doc.topics] == ["Identity", "Projects"]
    e = doc.find("flight seat")
    assert e and e.date == "2026-09-28" and "aisle" in e.body
    assert doc.topic("Projects").intro == "Intro line for projects."
    assert doc.find("Odie").body.startswith("Personal assistant") and "not a topic" in doc.find("Odie").body


def test_upsert_replace_and_append(tmp_path):
    mf = MemoryFile(tmp_path / "odie-memories.md", tmp_path / ".lock", "odie")
    mf.ensure()
    assert mf.path.read_text().startswith("---\ntitle: odie")
    mf.update("Flight Seat Preference", "Prefers aisle seats.", topic="Identity", source="test")
    mf.update("Flight Seat Preference", "Window is fine on short hops.", topic="Identity", source="test", append=True)
    doc = mf.load()
    e = doc.find("Flight Seat Preference")
    assert "aisle" in e.body and "short hops" in e.body and e.topic == "Identity"
    mf.update("Flight Seat Preference", "Aisle only.", source="test")  # replace, keeps topic
    assert mf.load().find("Flight Seat Preference").body == "Aisle only."
    assert (tmp_path / ".history" / "odie-memories-history.md").exists()
    assert mf.load().find("Nothing") is None


def test_untopiced_entry_lands_in_inbox(tmp_path):
    mf = MemoryFile(tmp_path / "m.md", tmp_path / ".lock", "odie")
    mf.update("Dentist", "Smile Dental, Koregaon Park.", source="chat")
    assert mf.load().find("Dentist").topic == "Inbox"


def test_index_and_prefetch():
    doc = parse(SAMPLE)
    idx = build_index(doc, max_chars=5000)
    assert "## Identity" in idx and "- Flight Seat Preference (2026-09-28)" in idx and "Asha prefers" not in idx
    hits = prefetch_hits(doc.entries(), "book me a seat on the flight to Zurich", limit=4)
    assert hits and hits[0].entry.title == "Flight Seat Preference"
    assert prefetch_hits(doc.entries(), "what is the weather", limit=4) == []
    text, used = render_prefetch(hits, max_entries=4, max_chars=2500)
    assert "aisle" in text and used == ["Flight Seat Preference"]
    assert search(doc.entries(), "pune")[0].entry.title == "Asha"


def test_review_parse_items():
    raw = 'Sure. [{"topic":"Identity","title":"Dentist","content":"Smile Dental."},{"title":"", "content":"x"}] done'
    assert parse_items(raw) == [{"topic": "Identity", "title": "Dentist", "content": "Smile Dental."}]
    assert parse_items("nothing here") == [] and parse_items("[]") == []


def test_memory_tools(tmp_path):
    from odie.memory.tools import make_memory_tools
    mf = MemoryFile(tmp_path / "m.md", tmp_path / ".lock", "odie")
    tools = {t.name: t for t in make_memory_tools(mf)}
    assert set(tools) == {"fetch_memory", "search_memories", "update_memory", "forget_memory"}
    assert "Saved" in tools["update_memory"].func(title="Dentist", content="Smile Dental.", topic="Health")
    assert "Smile Dental" in tools["fetch_memory"].func(title="dentist")
    assert "Dentist" in tools["search_memories"].func(query="dental appointment")
    assert "nothing" in tools["fetch_memory"].func(title="zebra").lower()
