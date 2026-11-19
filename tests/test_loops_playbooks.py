"""A playbook is a skill (proactive design §9): its SKILL.md says which loops it takes and each step's tier."""
import pytest

from odie.loops import playbooks


def test_github_pr_is_installed_and_read_only():
    book = playbooks.get("github-pr")
    assert book is not None and book.takes == ("pull request", "issue")
    assert book.steps == {"pr_facts": 0, "issue_facts": 0, "brief": 0, "test_pr": 1, "merge": 2}
    assert "Answer with JSON only" in book.text and "---" not in book.text
    assert playbooks.for_kind("Pull Request").name == "github-pr"
    assert playbooks.for_kind("bill") is None
    assert playbooks.get("nope") is None


def test_a_playbook_may_never_declare_tier_three(tmp_path):
    bad = tmp_path / "bad" / "SKILL.md"
    bad.parent.mkdir()
    bad.write_text("---\nname: bad\ndescription: x\ntakes: [order]\nsteps:\n  pay: 3\n---\nbody\n")
    with pytest.raises(ValueError):
        playbooks.load(bad)
