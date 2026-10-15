"""Checks that every request Odie sends a model only ADDS to the one before it, so the provider can reuse its prompt
cache (2026-10-12).

Every provider caches the start of a prompt: LM Studio and llama.cpp keep the computed start of the last prompt, Ollama
and OpenAI-style services do the same on their side, and Claude bills a repeated start at the cache rate. All of them
reuse only the part that is byte for byte the same as before. A request that changes something early (a shortened tool
result, a removed note, a new tool) makes the model read everything after that point again.

Two commands:

    scripts/prefix_check.sh <folder of saved requests>
        Compares each request with the one before it: APPEND-ONLY, or CHANGED at the first piece that differs, and how
        much of it could be reused (the characters before the first difference).

    scripts/prefix_check.sh run <provider>/<model> [--turns file] [--thinking] [--out folder]
        Replays a chat through Odie's real runner (odie.chat_replay, on a throwaway home), keeping EVERY request the
        model gets (Claude's too, with its input and cached token counts), then checks them. Saved under ./.measure/.

A request is read as pieces in the order the model reads them: the tools, the system prompt, then each message. Cache
marks (Claude's cache_control) are left out: where they sit moves from request to request and isn't part of the text.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEASURE = REPO / ".measure"


# ── Reading a saved request ────────────────────────────────────────────────────────────────────────────────────────

def _without_marks(value):
    """value minus Claude's cache_control marks, which move to the end of each request by design."""
    if isinstance(value, dict):
        return {k: _without_marks(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_without_marks(v) for v in value]
    return value


def _dump(value) -> str:
    return json.dumps(_without_marks(value), sort_keys=True, ensure_ascii=False)


def pieces(body: dict) -> list[tuple[str, str]]:
    """A request as (label, text) pieces in reading order: tools, system prompt, then each message.
    Both shapes Odie sends:
      OpenAI-style {"tools": [...], "messages": [{"role": "system", ...}, {"role": "user", ...}]}
        -> [("tools", …), ("message 0 (system)", …), ("message 1 (user)", …)]
      Claude {"tools": [...], "system": [...], "messages": [...]}
        -> [("tools", …), ("system", …), ("message 0 (user)", …)]"""
    out = [("tools", _dump(body.get("tools") or []))]
    if "system" in body:
        out.append(("system", _dump(body.get("system"))))
    for i, m in enumerate(body.get("messages") or []):
        kept = {k: m.get(k) for k in ("role", "content", "tool_calls", "tool_call_id") if k in m}
        out.append((f"message {i} ({m.get('role', '?')})", _dump(kept)))
    return out


# ── Comparing two requests ─────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Step:
    name: str          # the request's file name
    total: int         # characters in this request
    reusable: int      # characters at its start that are the same as the request before
    appended: bool     # True: the request before is all there, unchanged, at the start of this one
    where: str = ""    # the first piece that differs ("" when appended)
    was: str = ""      # that piece before (the first 140 characters from where they differ)
    now: str = ""      # that piece now

    @property
    def fresh(self) -> int:
        """Characters the model has to read anew."""
        return self.total - self.reusable

    @property
    def share(self) -> int:
        """The reusable part, in whole percent."""
        return self.reusable * 100 // self.total if self.total else 100


def _same_start(a: str, b: str) -> int:
    """How many characters a and b share at their start: ("abcd", "abxy") -> 2."""
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def compare(name: str, before: list[tuple[str, str]] | None, now: list[tuple[str, str]]) -> Step:
    """This request against the one before it. Worked example: before = [tools, system, user "hi"], now = [tools,
    system, user "hi", assistant "hello", user "time?"] -> appended, reusable = the length of all of `before`.
    now = [tools, system, user "hi (edited)", …] -> CHANGED at message 0, reusable = tools + system + the 'hi' they share."""
    total = sum(len(t) for _, t in now)
    if before is None:
        return Step(name, total, 0, True)
    reusable = 0
    for i, (label, text) in enumerate(now):
        if i >= len(before):
            return Step(name, total, reusable, True)
        old = before[i][1]
        if old == text:
            reusable += len(text)
            continue
        same = _same_start(old, text)
        if same == len(old) and i == len(before) - 1:
            return Step(name, total, reusable + same, True)  # the last piece grew at its end: still a pure addition
        return Step(name, total, reusable + same, False, label, old[same:same + 140], text[same:same + 140])
    return Step(name, total, reusable, len(now) >= len(before))


def check(folder: Path) -> list[Step]:
    """Every saved request in the folder (oldest first, by file name) against the one before it."""
    steps: list[Step] = []
    before = None
    for f in sorted(folder.glob("*.json")):
        body = json.loads(f.read_text())
        body = body.get("request", body)  # older Claude records kept the request beside its usage
        now = pieces(body)
        steps.append(compare(f.stem, before, now))
        before = now
    return steps


def usage_of(folder: Path) -> list[dict]:
    """Claude's token counts per request (from records `run` saves), in file order; [] for other providers."""
    out = []
    for f in sorted(folder.glob("*.json")):
        u = json.loads(f.read_text()).get("usage")
        if u:
            out.append(u)
    return out


def report(folder: Path) -> str:
    steps = check(folder)
    lines = [f"{len(steps)} requests in {folder}"]
    usage = usage_of(folder)
    for i, s in enumerate(steps):
        verdict = "APPEND-ONLY" if s.appended else f"CHANGED at {s.where}"
        tokens = ""
        if i < len(usage):
            u = usage[i]
            tokens = f"  [input {u.get('input_tokens', 0)}, cache read {u.get('cache_read_input_tokens', 0)}, cache write {u.get('cache_creation_input_tokens', 0)}]"
        lines.append(f"  {i + 1:>3}. {verdict:<34} reusable {s.share:>3}% of {s.total / 1000:.1f}k chars{tokens}")
        if not s.appended:
            lines.append(f"       was: {s.was!r}")
            lines.append(f"       now: {s.now!r}")
    total = sum(s.total for s in steps)
    fresh = sum(s.fresh for s in steps)
    changed = sum(1 for s in steps if not s.appended)
    lines.append(f"Total {total / 1000:.0f}k chars sent, {fresh / 1000:.0f}k read anew ({fresh * 100 // max(total, 1)}%); "
                 f"{changed} of {len(steps) - 1} requests changed something earlier.")
    return "\n".join(lines)


# ── Running a chat and keeping every request ───────────────────────────────────────────────────────────────────────

def run(argv: list[str]) -> int:
    """`run <provider>/<model> [--turns file] [--thinking] [--out folder]`: the chat replay, keeping every request."""
    import functools
    import os
    import shutil

    from odie import blocks_eval as be
    from odie import chat_replay
    target = argv[0]
    out = Path(chat_replay.option(argv, "--out") or MEASURE / f"{time.strftime('%Y%m%d-%H%M%S')}-{target.replace('/', '-').replace(':', '-')}")
    requests = out / "requests"
    out.mkdir(parents=True, exist_ok=True)
    os.environ["CHAT_REPLAY_DIR"] = str(out)  # the replay's own results land here too, not in evals/chats
    chat_replay.RESULTS_DIR = out
    homes: list[Path] = []
    set_home = be.use_throwaway_home

    def throwaway_home_keeping_requests(root: Path) -> None:
        set_home(root)  # only now may Odie's model code load its settings (for the throwaway home)
        homes.append(root)
        import odie.agent.model as model
        model.save_request = functools.partial(model.save_request, keep=10_000)  # every provider's, Claude's included (litellm)
    be.use_throwaway_home = throwaway_home_keeping_requests
    args = [a for i, a in enumerate(argv) if a != "--out" and (i == 0 or argv[i - 1] != "--out")]
    code = 1
    try:
        code = chat_replay.main(args)
    except Exception as e:  # noqa: BLE001 (the scoring step needs web/'s packages; the requests are kept anyway)
        print(f"the replay stopped: {type(e).__name__}: {e}")
    finally:
        if homes:
            from odie import config
            saved = config.settings.data_dir / "requests"  # the throwaway home's (checked by use_throwaway_home)
            for f in sorted(saved.glob("*.json")) if saved.is_dir() else []:
                requests.mkdir(parents=True, exist_ok=True)
                shutil.copy(f, requests / f.name)
    text = report(requests) if requests.is_dir() else "no requests were saved"
    (out / "prefix_check.txt").write_text(text + "\n")
    print(text)
    return code


def main(argv: list[str]) -> int:
    if argv and argv[0] == "run" and len(argv) > 1:
        return run(argv[1:])
    if len(argv) == 1 and Path(argv[0]).is_dir():
        print(report(Path(argv[0])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
