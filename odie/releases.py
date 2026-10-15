"""What an update moves to, and how the running version is named.

An install follows either the releases (the default: the newest tag like v0.2.0) or a branch (ODIE_BRANCH=main, for
someone working on Odie itself). Both `odie update` (odie/cli.py) and the app's "Check now" (odie/update.py) ask
these functions, so the two always agree.
"""
from __future__ import annotations

import re

RELEASES = "releases"  # the ODIE_BRANCH value that means "the newest release", not a branch
_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def follows_releases(branch: str) -> bool:
    """Whether this install updates to releases rather than a branch.
    Example: "releases" -> True; "" (unset) -> True; "main" -> False."""
    return branch in ("", RELEASES)


def newest_release(tags: list[str]) -> str | None:
    """The newest release among git's tags, by version number; other tags are ignored.
    Example: ["v0.1.0", "v0.10.0", "v0.2.0", "film-take-3"] -> "v0.10.0"; ["v0.2.0-rc1"] -> None; [] -> None."""
    releases = []
    for tag in tags:
        parts = _RELEASE_TAG.match(tag.strip())
        if parts:
            number = tuple(int(p) for p in parts.groups())
            releases.append((number, tag.strip()))
    if not releases:
        return None
    return max(releases)[1]


def version_label(described: str) -> str:
    """A readable version from `git describe --tags --always`.
    Example: "v0.1.0" -> "0.1.0" (a release); "v0.1.0-3-gce33450" -> "0.1.0+3 (ce33450)" (three commits after it);
    "ce33450" -> "ce33450" (no release yet); "" -> "unknown"."""
    text = described.strip()
    if not text:
        return "unknown"
    after_release = re.match(r"^v(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$", text)
    if after_release:
        number, commits, commit = after_release.groups()
        return f"{number}+{commits} ({commit[:7]})"
    release = _RELEASE_TAG.match(text)
    if release:
        return text[1:]
    return text[:7]
