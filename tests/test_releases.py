"""Which release an update moves to, and how the running version is named (odie/releases.py)."""
from odie.releases import follows_releases, newest_release, version_label


def test_follows_releases_unless_a_branch_is_named():
    assert follows_releases("releases") and follows_releases("")
    assert not follows_releases("main")


def test_newest_release_is_by_version_number_and_ignores_other_tags():
    assert newest_release(["v0.1.0", "v0.10.0", "v0.2.0", "film-take-3"]) == "v0.10.0"
    assert newest_release(["v0.2.0-rc1"]) is None
    assert newest_release([]) is None


def test_version_label():
    assert version_label("v0.1.0\n") == "0.1.0"
    assert version_label("v0.1.0-3-gce33450") == "0.1.0+3 (ce33450)"
    assert version_label("ce33450") == "ce33450"
    assert version_label("") == "unknown"
