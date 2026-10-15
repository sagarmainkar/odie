"""The block catalogue: every visual block the app can draw, what it's for, its fields and an example. The system
prompt carries it (visuals_prompt) and the skill builder reads it to know which visuals a skill can use. The app's
#sample screen shows the blocks in use, in one recorded conversation (evals/sample)."""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path

CATALOG = Path(__file__).with_name("catalog.json")

# The chart block's kinds (CHART_KINDS in web/src/components/chartData.ts). An ```odie-chart fence names its kind as
# "type", so these are allowed there though they aren't blocks. A chart's more_examples (one per kind) document the
# kinds; the prompt carries its one example.
CHART_KINDS = {"line", "bar", "area", "stacked", "hbar", "combo", "pie", "donut"}


@cache
def load_catalog() -> dict:
    return json.loads(CATALOG.read_text())


def kinds() -> set[str]:
    return {b["kind"] for b in load_catalog()["blocks"]}


def _group(block: dict) -> str:
    """Which part of the catalogue an entry belongs to: a ready-made block (the default), a container or an atom."""
    return block.get("group", "block")


def _entry_text(b: dict) -> list[str]:
    """A block or container in full: what it's for, when to use it, its fields and an example."""
    fence = b.get("fence", "odie-blocks")
    heading = f"### {b['kind']}" + ("" if fence == "odie-blocks" else f" (```{fence})")
    return [heading, f"For: {b['for']}", f"Use when: {b['use_when']}", f"Fields: {b['fields']}",
            "Example: " + json.dumps(b["example"], ensure_ascii=False), ""]


def _atom_line(b: dict) -> str:
    """An atom on one line (they are small, and the model needs only the shape): '- badge: A small pill. Fields: … {…}'"""
    return f"- {b['kind']}: {b['for']} Fields: {b['fields']} " + json.dumps(b["example"], ensure_ascii=False)


def catalog_text() -> str:
    """The catalogue as short Markdown for a model writing a skill: ready-made blocks, then containers, atoms and the
    inline syntax."""
    c = load_catalog()
    out = [c["about"], ""]
    for b in c["blocks"]:
        if _group(b) == "block":
            out += _entry_text(b)
    out += ["## Containers", c["containers"], ""]
    for b in c["blocks"]:
        if _group(b) == "container":
            out += _entry_text(b)
    out += ["## Atoms", c["atoms"]]
    out += [_atom_line(b) for b in c["blocks"] if _group(b) == "atom"]
    out += ["", "## Inline", c["inline"], c["shared_values"], ""]
    out.append("Icon names: " + ", ".join(c["icons"]))
    return "\n".join(out)


VISUALS_HEADING = "Visual blocks (the app draws these; write them right in your reply, no skill to load):"


def visuals_prompt() -> str:
    """The catalogue as it sits in the system prompt, on every request (2026-10-12): a heading, one line on when to
    draw, then catalog_text(). It used to be the visuals skill, loaded mid-turn (by the model, or preloaded for
    questions that looked drawable), which changed what the model had already read and broke every provider's prompt
    cache; in the system prompt it's read once and then comes from the cache. About 3,300 tokens."""
    return (f"{VISUALS_HEADING}\nUse a block only when it reads better than prose, with a sentence or two of text. Write "
            "the JSON exactly as shown. Use only real facts (from tools or the user).\n\n" + catalog_text())
