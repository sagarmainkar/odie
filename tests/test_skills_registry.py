"""How skills are shown in Settings → Skills (odie.skills.registry)."""


def test_settings_shows_a_title_and_a_line_written_for_people(tmp_path):
    """Built-in skills carry their own title and summary; a user's skill gets its name tidied and its description up
    to where it starts telling the model when to use it."""
    from odie.skills.registry import SkillEntry, discover, shown_as
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    builtins = {e.name: shown_as(e) for e in discover(s)}
    assert builtins["about-odie"][0] == "About Odie" and "Use for" not in builtins["about-odie"][1]
    assert all("Use for" not in summary and "the user" not in summary for _, summary in builtins.values())
    mine = SkillEntry("weekly-review", 'A Sunday review of my week. Use for "review my week".', "user", "ok", [])
    assert shown_as(mine) == ("Weekly review", "A Sunday review of my week.")
