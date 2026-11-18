"""The rail on test_pr (proactive design §7 step 4, §16): code decides whether a pull request's tests may run on this
computer, from fresh `gh` facts only, never from what the model or a mail says. Allowed only when all hold:
  - it is HIS pull request (`yours`: the signed-in login wrote it) on HIS repo (the repo's owner is that login);
  - it is open and its head is not from a fork (`isCrossRepository` false);
  - it leaves dependency and lock files alone (DEPENDENCY_NAMES / DEPENDENCY_GLOBS, read from `gh pr view --json
    files`), so the test installs only what he already runs: a dependency bump run locally would install strangers' code;
  - he approved that repo's test command once (odie.loops.recipes).
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
    ".nvmrc", ".node-version", ".tool-versions",
})
DEPENDENCY_GLOBS = ("requirements*.txt", "constraints*.txt", "*.gemspec", "*.csproj", "build.gradle*",
                    "settings.gradle*", ".yarnrc*", "rust-toolchain*")
NO_RECIPE = "no test command is approved for this repo yet"


def dependency_files(paths: list[str]) -> list[str]:
    """The paths that are dependency or lock files: ["app.py", "web/package-lock.json"] -> ["web/package-lock.json"];
    ["requirements-dev.txt"] -> it; ["docs/requirements.md"] -> []; ["tests/test_lock.py"] -> []."""
    out = []
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if name in DEPENDENCY_NAMES or any(fnmatch(name, pattern) for pattern in DEPENDENCY_GLOBS):
            out.append(path)
    return out


def why_not(facts: dict, recipe: str | None) -> str | None:
    """Why this pull request may not be tested here, or None when it may. The checks, in order:
      his own, open, from his repo's branch, lockfile untouched, recipe approved -> None
      written by bob                          -> "it isn't your pull request (bob wrote it)"
      his, but on example/app (not his repo)  -> "it isn't on your own repo"
      from a fork                             -> "it comes from a fork"
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
    touched = dependency_files(facts.get("paths") or [])
    if touched:
        return f"it changes dependency files ({', '.join(touched[:3])})"
    if facts.get("state") != "open":
        return "it isn't open"
    if not SHA_RE.match(facts.get("head_sha") or ""):
        return "GitHub gave no head commit"
    if not recipe:
        return NO_RECIPE
    return None
