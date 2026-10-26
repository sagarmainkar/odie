from odie.blocks import catalog_text, kinds, load_catalog
from tests.test_api import client  # noqa: F401  (fixture)


def test_catalog_lists_every_kind_once_with_an_example():
    c = load_catalog()
    names = [b["kind"] for b in c["blocks"]]
    assert len(names) == len(set(names))
    assert {"chart", "kpis", "actions", "source", "tiles", "progress", "streak", "flip", "heatmap", "timeline", "images", "form"} <= kinds()
    assert {"table", "list", "checklist", "calculator", "callout", "row", "section", "grid", "heading", "text", "badge", "button", "link", "image",
            "stat", "bar", "divider"} <= kinds()
    for b in c["blocks"]:
        assert b["for"] and b["use_when"] and b["fields"] and b["example"]
        if b.get("fence", "odie-blocks") == "odie-blocks":
            assert b["example"]["type"] == b["kind"]


def test_catalog_text_is_readable_for_a_model():
    t = catalog_text()
    assert "### timeline" in t and "### images (```odie-images)" in t and "Icon names:" in t
    assert "### table" in t and "## Containers" in t and "### section" in t and "## Atoms" in t and "- badge:" in t
    assert ":badge[" in t and ":icon[" in t  # the inline syntax is explained
    assert "### checklist" in t and "### calculator" in t and "emi(principal, rate_pct, years)" in t
    assert "{round(emi(p, r, n)" in t  # shared values are explained


def test_the_catalogue_stays_within_its_token_budget():
    """The spec allowed the visuals skill about 3,200 tokens; ~4 chars a token. Raised to 3,300 with the calculator,
    and to 3,600 with flip and heatmap (13 Oct 2026), to 3,750 with the svg drawing (14 Oct 2026), and to 4,000 with the
    form (26 Oct 2026; the owner's call: the system prompt is cached by the providers, so the extra cost is small).
    Since 12 Oct 2026 it's in the system prompt on every request (read once, then from the provider's cache)."""
    from odie.blocks import visuals_prompt
    assert len(visuals_prompt()) / 4 <= 4000


def test_the_form_tells_the_model_when_to_use_it_and_how_answers_come_back():
    form = next(b for b in load_catalog()["blocks"] if b["kind"] == "form")
    assert form.get("group", "block") == "block"
    assert form["for"] == ("A small form the user fills in and sends: dropdowns, radio buttons, checkboxes, text and sliders, "
                           "prefilled with your best guess.")
    assert form["use_when"].startswith("You need two or more answers from the user at once")
    assert "Prefill every field with your best suggestion." in form["use_when"] and "use actions" in form["use_when"]
    assert "odie-form-answer block: read values by field id" in form["use_when"]
    assert {f["kind"] for f in form["example"]["fields"]} <= {"select", "radio", "checkbox", "text", "slider"}
    assert len(form["example"]["fields"]) == 3  # short, to save tokens


def test_the_form_entry_stays_short():
    """The form's entry as the prompt carries it. The brief aimed at about 220 tokens; its own wording for `for` and
    `use_when` is about 140 of them, so with the field list and a three-field example it measures about 290 (26 Oct
    2026). The whole catalogue still fits its 4,000 budget, so no other entry needed trimming."""
    from odie.blocks import _entry_text
    form = next(b for b in load_catalog()["blocks"] if b["kind"] == "form")
    assert len("\n".join(_entry_text(form))) / 4 <= 300


async def test_catalog_route(client):
    c = client[0] if isinstance(client, tuple) else client
    r = await c.get("/api/blocks/catalog")
    assert r.status_code == 200 and "tiles" in {b["kind"] for b in r.json()["blocks"]}


def test_the_catalogue_is_in_the_system_prompt_not_a_skill(isolated_settings, tmp_path):
    """The blocks are in the system prompt, the same on every request, and there's no visuals skill to load mid-turn
    (loading it changed what the model had already read, so every provider's prompt cache broke)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.agent.prompt import Who, build_static_prompt
    from odie.blocks import catalog_text
    from odie.skills.registry import discover
    from odie.store.db import Store
    now = datetime(2026, 10, 12, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    prompt = build_static_prompt(now, None, "", who=Who())
    assert catalog_text() in prompt
    assert prompt.index(catalog_text()) < prompt.index("Today is")  # the part that never changes comes first
    store = Store(tmp_path / "a.db")
    store.init_schema()
    assert "visuals" not in {e.name for e in discover(store)}


def test_chart_kinds_match_the_app():
    """The chart kinds Python allows are the ones the app draws (CHART_KINDS in web/src/components/chartData.ts)."""
    import re
    from pathlib import Path

    from odie.blocks import CHART_KINDS
    source = (Path(__file__).parent.parent / "web" / "src" / "components" / "chartData.ts").read_text()
    listed = re.search(r"CHART_KINDS = \[([^\]]*)\]", source).group(1)
    assert set(re.findall(r'"(\w+)"', listed)) == CHART_KINDS


def test_chart_gallery_examples_stay_out_of_the_prompt():
    """Each new chart kind has an example for the #blocks page, but the prompt carries only the chart's one example
    (and names the kinds in its fields)."""
    chart = next(b for b in load_catalog()["blocks"] if b["kind"] == "chart")
    assert {e["kind"] for e in chart["more_examples"]} == {"pie", "donut", "stacked", "hbar", "area", "combo"}
    t = catalog_text()
    assert "kind: line | bar | pie | donut | stacked | hbar | area | combo" in t
    assert "Portfolio mix" not in t and "more_examples" not in t


def test_a_skill_may_write_any_chart_kind():
    from odie.skills import builder
    assert builder.check_text('```odie-chart {"type": "donut", "x": []}', []) == []
    assert builder.check_text('{"type": "radar"}', []) != []
