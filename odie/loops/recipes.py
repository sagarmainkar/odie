"""Test recipes (proactive design §16): the command that runs a repo's tests, approved ONCE per repo by his tap.

Code proposes it, never the model: from the names at the repo's top level, by a fixed table (TABLE). The offer is a
card on the loop's owner's Pulse ("I'd test example/app with `uv run pytest -q`. [Use this] [No]"); Use this keeps the
command for that repo (`loops.recipes`), No keeps that he said no, and Odie doesn't ask again (it briefs from CI).
Nothing from a pull request, a mail or the model ever becomes part of a command."""
from __future__ import annotations

from datetime import datetime

KEY = "loops.recipes"  # {"example/app": {"command": "uv run pytest -q", "at": "…"}} or {"declined": true, "at": "…"}
OFFERS = "loops.recipe_offers"  # {"example/app": {"command": …, "loop_id": 3, "owner": "", "at": "…"}}
# The first row whose file is at the top of the repo gives the command.
TABLE = (("uv.lock", "uv run pytest -q"), ("pyproject.toml", "uv run pytest -q"),
         ("package.json", "npm ci && npm test"), ("Cargo.toml", "cargo test"), ("go.mod", "go test ./..."),
         ("Makefile", "make test"))


def suggest(root_names: list[str]) -> str | None:
    """The command code would propose: ["README.md", "pyproject.toml", "uv.lock"] -> "uv run pytest -q";
    ["package.json"] -> "npm ci && npm test"; ["Cargo.toml"] -> "cargo test"; ["README.md"] -> None (no idea)."""
    names = set(root_names)
    for name, command in TABLE:
        if name in names:
            return command
    return None


def runnable(command: str | None) -> bool:
    """Whether a command may run as a test at all: only one of TABLE's, as written. "uv run pytest -q" -> True;
    "sh test.sh" or anything stored by other means -> False (a recipe is never a free string)."""
    return command in {c for _, c in TABLE}


def _all(store) -> dict:
    return store.get_setting(KEY) or {}


def approved(store, repo: str) -> str | None:
    """The command he approved for this repo, or None (never asked, he said No, or what is kept isn't runnable)."""
    kept = _all(store).get(repo) or {}
    command = kept.get("command")
    if not runnable(command):
        return None
    return command


def declined(store, repo: str) -> bool:
    return bool((_all(store).get(repo) or {}).get("declined"))


def approve(store, repo: str, command: str, now: datetime) -> None:
    """Keeps the command for the repo; one that isn't runnable raises ValueError."""
    if not runnable(command):
        raise ValueError(f"not a test command Odie runs: {command!r}")
    kept = _all(store)
    kept[repo] = {"command": command, "at": now.isoformat(timespec="seconds")}
    store.set_setting(KEY, kept)


def offer(store, repo: str, command: str, loop: dict, now: datetime) -> None:
    """The card asking him to approve this command for this repo, on the loop's owner's Pulse (one per repo)."""
    offers = store.get_setting(OFFERS) or {}
    offers[repo] = {"command": command, "loop_id": loop["id"], "owner": loop["personality"],
                    "at": now.isoformat(timespec="seconds")}
    store.set_setting(OFFERS, offers)


def offered(store, repo: str) -> dict | None:
    return (store.get_setting(OFFERS) or {}).get(repo)


def _take_offer(store, repo: str) -> dict | None:
    offers = store.get_setting(OFFERS) or {}
    found = offers.pop(repo, None)
    store.set_setting(OFFERS, offers)
    return found


def use(store, repo: str, now: datetime) -> int | None:
    """His tap on Use this: the offered command (as the card showed it, kept here, never sent by the app) becomes the
    repo's recipe, and the loop that asked is looked at again at once. Returns that loop's id; None with no offer."""
    from odie.loops import ledger
    found = _take_offer(store, repo)
    if found is None:
        return None
    approve(store, repo, found["command"], now)
    store.audit("user", "test_recipe_approved", result_summary=f"{repo}: {found['command']}")
    loop = ledger.get(store, found["loop_id"])
    if loop is not None and loop["state"] in ledger.OPEN:
        ledger.update(store, loop["id"], now, has_news=1, next_check_at=now.isoformat(timespec="seconds"))
    return found["loop_id"]


def decline(store, repo: str, now: datetime) -> int | None:
    """His No: never asked again for this repo; the loop that asked is looked at again (it briefs from CI)."""
    from odie.loops import ledger
    found = _take_offer(store, repo)
    kept = _all(store)
    kept[repo] = {"declined": True, "at": now.isoformat(timespec="seconds")}
    store.set_setting(KEY, kept)
    if found is None:
        return None
    loop = ledger.get(store, found["loop_id"])
    if loop is not None and loop["state"] in ledger.OPEN:
        ledger.update(store, loop["id"], now, has_news=1, next_check_at=now.isoformat(timespec="seconds"))
    return found["loop_id"]


def card(repo: str, found: dict) -> dict:
    """An offer as a Pulse card, its buttons written here: Use this, No."""
    return {"ref": f"recipe:{repo}", "title": f"Test {repo}?", "why": f"I'd test {repo} with `{found['command']}`.",
            "brief": ("Only your own pull requests, on a repo only you can push to, every commit yours, dependency files "
                      "untouched. In a fresh copy, in a sandbox: it reads only the system, its tools and that copy (none "
                      "of your files, keys or Odie), writes only to the copy, and reaches nothing on this computer; it "
                      "can reach the internet and other devices on your network."),
            "icon": "terminal", "badge": "", "ask": f"How would you test {repo}?",
            "main": {"label": "Use this", "action": "recipe_use", "value": repo},
            "other": {"label": "No", "action": "recipe_no", "value": repo}, "pile": "alerts",
            "since": found.get("at") or "", "decide": True}


def cards(store, owner: str) -> list[dict]:
    """The offers waiting on this owner's Pulse."""
    offers = store.get_setting(OFFERS) or {}
    return [card(repo, found) for repo, found in offers.items() if (found.get("owner") or "") == owner]
