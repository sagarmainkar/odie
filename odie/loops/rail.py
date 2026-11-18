"""The rail on test_pr (proactive design §7 step 4, §16): code decides whether a pull request's tests may run on this
computer, from fresh `gh` facts only, never from what the model or a mail says. Allowed only when all hold:
  - it is HIS pull request (`yours`: the signed-in login wrote it) on HIS repo (the repo's owner is that login);
  - it is open and its head is not from a fork (`isCrossRepository` false);
  - every commit on it is his (its author's GitHub login is the signed-in one): a commit by someone else, or by an
    author GitHub knows no account for, -> briefed only;
  - GitHub listed every file it changes (it lists at most 100): more files than listed -> briefed only;
  - it leaves dependency, lock and package-tool config files alone (DEPENDENCY_NAMES / DEPENDENCY_GLOBS /
    DEPENDENCY_PATHS, read from `gh pr view --json files`), so the test installs only what he already runs: a
    dependency bump run locally would install strangers' code; and submodules (.gitmodules: code from elsewhere);
  - it leaves alone what the approved command itself runs (COMMAND_FILES: a changed Makefile for `make test`);
  - he approved that repo's test command once (odie.loops.recipes).
Ignored on purpose: CI config (.github/workflows: it runs on GitHub, not here) and git hooks (never in a clone).
Otherwise the step is refused with the reason, and the model briefs from GitHub's own CI result."""
from __future__ import annotations

from fnmatch import fnmatch

from odie.loops.github import SHA_RE

# Dependency and lock files, matched on a file's own name wherever it sits (a monorepo's web/package.json too):
# Python, JavaScript, Rust, Go, Ruby, PHP, Java/Kotlin, Elixir, Swift, .NET and Dart manifests and lockfiles, and the
# files that pick a toolchain version (a new one would be downloaded and run).
DEPENDENCY_NAMES = frozenset({
    "pyproject.toml", "uv.lock", "poetry.lock", "pdm.lock", "Pipfile", "Pipfile.lock", "setup.py", "setup.cfg",
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "pnpm-workspace.yaml",
    "bun.lock", "bun.lockb", ".npmrc", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "go.work", "Gemfile",
    "Gemfile.lock", "composer.json", "composer.lock", "pom.xml", "gradle.lockfile", "mix.exs", "mix.lock",
    "Package.swift", "Package.resolved", "packages.lock.json", "pubspec.yaml", "pubspec.lock", ".python-version",
    ".nvmrc", ".node-version", ".tool-versions", "uv.toml", "pip.conf", ".pdm.toml", "pdm.toml", ".gitmodules",
})
DEPENDENCY_PATHS = (".cargo/config", ".cargo/config.toml")  # matched on the path's end: package tools' own config
# Files the approved command itself runs, by the command's first word: a change there changes what runs.
COMMAND_FILES = {"make": ("Makefile", "makefile", "GNUmakefile", "*.mk")}
DEPENDENCY_GLOBS = ("requirements*.txt", "constraints*.txt", "*.gemspec", "*.csproj", "build.gradle*",
                    "settings.gradle*", ".yarnrc*", "rust-toolchain*")
NO_RECIPE = "no test command is approved for this repo yet"


def dependency_files(paths: list[str]) -> list[str]:
    """The paths that are dependency or lock files: ["app.py", "web/package-lock.json"] -> ["web/package-lock.json"];
    ["requirements-dev.txt"] -> it; ["docs/requirements.md"] -> []; ["tests/test_lock.py"] -> []."""
    out = []
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        by_name = name in DEPENDENCY_NAMES or any(fnmatch(name, pattern) for pattern in DEPENDENCY_GLOBS)
        by_path = any(path == p or path.endswith("/" + p) for p in DEPENDENCY_PATHS)
        if by_name or by_path:
            out.append(path)
    return out


def command_files(paths: list[str], recipe: str | None) -> list[str]:
    """The changed files the approved command itself runs: `make test` with a changed Makefile or rules.mk -> those;
    `uv run pytest -q` -> [] (pyproject.toml is already a dependency file); no recipe -> []."""
    if not recipe:
        return []
    patterns = COMMAND_FILES.get(recipe.split()[0], ())
    return [p for p in paths if any(fnmatch(p.rsplit("/", 1)[-1], pattern) for pattern in patterns)]


def strangers(commit_authors: list[str], you: str) -> list[str]:
    """The commit authors that aren't him, in words: ["asha-dev", "bob"] with you "asha-dev" -> ["bob"]; an author
    with no GitHub account -> "an unknown author"."""
    out = []
    for login in commit_authors:
        if login.lower() == (you or "").lower() and login:
            continue
        word = login or "an unknown author"
        if word not in out:
            out.append(word)
    return out


def why_not(facts: dict, recipe: str | None) -> str | None:
    """Why this pull request may not be tested here, or None when it may. The checks, in order:
      his own, open, from his repo's branch, lockfile untouched, recipe approved -> None
      written by bob                          -> "it isn't your pull request (bob wrote it)"
      his, but on example/app (not his repo)  -> "it isn't on your own repo"
      from a fork                             -> "it comes from a fork"
      a commit by bob                         -> "it has commits by someone else (bob)"
      140 files changed, 100 listed           -> "it changes more files than GitHub listed (100 of 140)"
      changes the Makefile, recipe `make test` -> "it changes what `make test` runs (Makefile)"
      changes uv.lock                         -> "it changes dependency files (uv.lock)"
      merged or closed                        -> "it isn't open"
      no 40-character head commit             -> "GitHub gave no head commit"
      everything fine but no approved command -> NO_RECIPE (code offers one for his tap)"""
    if not facts.get("yours"):
        author = facts.get("author") or "someone else"
        return f"it isn't your pull request ({author} wrote it)"
    if not facts.get("on_your_repo"):
        return "it isn't on your own repo"
    if facts.get("from_fork"):
        return "it comes from a fork"
    commit_authors = facts.get("commit_authors") or []
    if not commit_authors:
        return "GitHub gave no commits"
    others = strangers(commit_authors, facts.get("you", ""))
    if others:
        return f"it has commits by someone else ({', '.join(others[:3])})"
    paths = facts.get("paths") or []
    if int(facts.get("files") or 0) > len(paths):
        return f"it changes more files than GitHub listed ({len(paths)} of {facts.get('files')})"
    touched = dependency_files(paths)
    if touched:
        return f"it changes dependency files ({', '.join(touched[:3])})"
    runs = command_files(paths, recipe)
    if runs:
        return f"it changes what `{recipe}` runs ({', '.join(runs[:3])})"
    if facts.get("state") != "open":
        return "it isn't open"
    if not SHA_RE.match(facts.get("head_sha") or ""):
        return "GitHub gave no head commit"
    if not recipe:
        return NO_RECIPE
    return None
