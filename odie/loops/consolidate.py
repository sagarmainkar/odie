"""Stage 2, Consolidate (proactive design §5): one loop per real thing. Right after a check, one model call sees the
check's findings from every source together, next to the loops Odie follows (one line each), the loops the user
finished lately, his own open reminders, his Watch for and Now lists and what Odie remembers of him; for each finding
it answers: the same as loop N (or as another finding, or as one of his reminders), new, closes loop N, or nothing.

The model thinks, code keeps it safe (§3). The call has no tools: it can only answer, and code writes its answer to
the ledger, nothing else. Code also keeps the rails:
  - the same-ID shortcut is shown as a hint ("loop #3 holds thread:t1"), and stands when the model gives no answer
    (a finding the check saw finished then closes the loop its ID ties it to);
  - unsure (no answer, a loop that isn't this owner's) -> a new loop: a duplicate beats a wrong merge;
  - a thing he finished with Done stays finished: news about it attaches quietly (no card, no reminder, no push).
    Only an answer that names the finished loop ("after": N) opens a new one, which says so in its Why. A finding
    whose own ID a finished loop holds can't be "new" without that;
  - one loop per pull request: a GitHub name an open loop holds is always that loop;
  - a reminder (a finding's remind_at) is made only for a NEW loop, or moved on an open one that has one;
  - a close always cites its evidence.
A call that fails or can't be read is asked once more; then the findings wait for the next check (pending), and after
PENDING_TRIES they are placed by the shortcut alone (else new)."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from odie.agent.callbacks import wrap_untrusted
from odie.loops import budget, findings, github, ledger, playbooks

log = logging.getLogger("odie.loops")
SKILL = Path(__file__).parent / "skill" / "SKILL.md"  # the consolidate skill: the owner reads and edits it
ANSWERS = ("same", "new", "closes", "nothing")
PENDING = "loops.pending"  # per owner (odie.watch.owner.key): findings waiting for a stage 2 that failed
PENDING_TRIES = 3
TASKS_SHOWN = 30
FINISHED_SHOWN = 30
OPEN_SHOWN = 60  # the design's 60 open loops per personality


def instruction() -> str:
    """The skill's text, the part the owner reads and edits (after its front matter)."""
    return SKILL.read_text().split("---", 2)[-1].strip()


def strong_refs(found: dict) -> list[str]:
    """The IDs of a finding the shortcut matches on: its mail, the mail's thread, an event, a pull request (not a
    loose order number the model wrote). ["mail:m1", "thread:t1", "order:A-1", "example/app#49"] -> all but order:A-1."""
    out = []
    for ref in found["refs"]:
        is_prefixed = ref.split(":", 1)[0] in ("mail", "thread", "event", "task", "note")
        if is_prefixed or github.parse(ref) is not None:
            out.append(ref)
    return out


def hints(store, pid: str, found: list[dict]) -> dict[str, dict]:
    """What the same-ID shortcut knows about each finding: {"F1": {"open": 3}} (an open loop holds one of its IDs),
    {"F2": {"finished": 2}} (a loop he finished holds one), {"F3": {"finding": "F1"}} (it shares an ID with an
    earlier finding of this check), or {} for none."""
    out: dict[str, dict] = {}
    seen: dict[str, str] = {}
    for f in found:
        refs = strong_refs(f)
        hint: dict = {}
        held = ledger.find_by_refs(store, pid, refs)
        if held is not None:
            hint = {"open": held["id"], "ref": sorted(set(refs) & set(held["refs"]))[0]}
        else:
            stopped = ledger.find_done_by_user(store, pid, refs)
            if stopped is not None:
                hint = {"finished": stopped["id"], "ref": sorted(set(refs) & set(stopped["refs"]))[0]}
        if not hint:
            earlier = next((seen[r] for r in refs if r in seen), None)
            if earlier is not None:
                hint = {"finding": earlier}
        for r in refs:
            seen.setdefault(r, f["id"])
        out[f["id"]] = hint
    return out


def hint_words(hint: dict) -> str:
    """A hint as the prompt says it: {"open": 3, "ref": "thread:t1"} -> "loop #3 holds thread:t1"; {"finished": 2,
    "ref": "event:u1"} -> "the user finished #2, which holds event:u1"; {"finding": "F1"} -> "shares an ID with F1"."""
    if "open" in hint:
        return f"loop #{hint['open']} holds {hint['ref']}"
    if "finished" in hint:
        return f"the user finished #{hint['finished']}, which holds {hint['ref']}"
    if "finding" in hint:
        return f"shares an ID with {hint['finding']}"
    return ""


def his_tasks(store, pid: str) -> list:
    """His own open reminders and to-dos (not the ones Odie made for a loop): the ledger reads them so it never opens
    a second loop for something he already noted."""
    mine, values = ledger._whose(pid)
    rows = store.query(f"select id, title, due_at, source_kind from tasks where status in ('open','waiting') and {mine} "
                       "order by id desc", values)
    own = [r for r in rows if (r["source_kind"] or "") not in ledger.ODIES_TASKS]
    return own[:TASKS_SHOWN]


def prompt_for(store, pid: str, now: datetime, found: list[dict], shortcut: dict[str, dict], context: dict) -> str:
    """What stage 2 reads. Everything that carries other people's words (findings, loop titles and evidence, his
    reminders' titles, which may have come from mail) is fenced; his Watch for, Now and memory are his own."""
    finding_lines = [findings.line(f, hint_words(shortcut.get(f["id"], {}))) for f in found]
    open_lines = [ledger.line(lp, ledger.events(store, lp["id"])) for lp in ledger.open_loops(store, pid)[-OPEN_SHOWN:]]
    done_lines = [ledger.finished_line(lp) for lp in ledger.finished(store, pid, now)[:FINISHED_SHOWN]]
    task_lines = []
    for t in his_tasks(store, pid):
        text = f"task #{t['id']} {t['title']}"
        if t["due_at"]:
            text += f" · due {t['due_at'][:16]}"
        task_lines.append(text)
    parts = [f"Findings from this check:\n{wrap_untrusted(chr(10).join(finding_lines))}",
             f"Open loops:\n{wrap_untrusted(chr(10).join(open_lines) or '(none)')}",
             f"Loops the user finished with Done (last {ledger.FINISHED_DAYS} days):\n"
             f"{wrap_untrusted(chr(10).join(done_lines) or '(none)')}",
             f"The user's own reminders and to-dos:\n{wrap_untrusted(chr(10).join(task_lines) or '(none)')}",
             f"Watch for:\n{context.get('watch') or '(nothing)'}",
             f"Now:\n{context.get('now') or '(nothing)'}",
             f"What you remember about the user:\n{context.get('memory') or '(nothing)'}"]
    return "\n\n".join(parts)


def parse(text: str) -> dict[str, dict] | None:
    """The model's answers by finding: {"F1": {"is": "same", "loop": 3, …}, …}, from the first JSON object (or list)
    in its reply; None when there is none it can read. An answer whose "is" isn't one of same/new/closes/nothing is
    left out (that finding then goes by the shortcut, else new).
      '{"answers": [{"f": "F1", "is": "same", "loop": 3}]}' -> {"F1": {"is": "same", "loop": 3, …}}
      '[{"f": "F2", "is": "new", "title": "Pay rent"}]' -> {"F2": {...}};  "no idea" -> None"""
    found = re.search(r"[\[{].*[\]}]", text or "", re.S)
    if found is None:
        return None
    try:
        raw = json.loads(found.group(0))
    except ValueError:
        return None
    if isinstance(raw, dict):
        raw = raw.get("answers")
    if not isinstance(raw, list):
        return None
    out: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("f") or item.get("finding_id") or "").strip()
        verdict = str(item.get("is") or "").strip().lower()
        if not key or verdict not in ANSWERS:
            continue
        out[key] = {**item, "is": verdict}
    return out


def number(value) -> int | None:
    """A loop or task number as the model wrote it: 3, "3", "#3" -> 3; "three", None -> None."""
    text = str(value if value is not None else "").strip().lstrip("#")
    if text.isdigit():
        return int(text)
    return None


class Applied:
    """What one stage 2 did, for the check: the loops that became cards and should push, the reminders made, and
    whether a reminder went to something he had already finished (then a told note isn't told)."""

    def __init__(self):
        self.opened: list[int] = []
        self.changed: list[int] = []
        self.closed: list[int] = []
        self.quiet: list[int] = []  # findings attached quietly to a loop he (or Odie) had closed
        self.to_push: list[int] = []
        self.reminders = 0
        self.reminder_to_finished = False
        self.placed: dict[str, int] = {}  # finding id -> the loop it went to


def evidence_of(found: dict) -> str:
    """A finding as one line of evidence: "Send the deck by Friday: Asha asks for it by Friday"; a done one:
    "Order: lamp: delivered 23 Oct"."""
    text = found["title"]
    detail = found["done"] or found["why"]
    if detail and detail not in text:
        text = f"{text}: {detail}"
    return text


def source_of(found: dict) -> str:
    """Where a finding came from, for its evidence line: "mail:m1" -> "mail"; "event:e1" -> "calendar"; else "watch"."""
    if found["ref"].startswith("mail:"):
        return "mail"
    if found["ref"].startswith("event:"):
        return "calendar"
    return "watch"


def state_for(owner: str, playbook: str) -> str:
    """Where a new loop starts: a playbook's loop goes to stage 4 ("new"); his move is a card ("ready"); waiting on
    someone, or Odie following alone, is "waiting" (under "Odie is on it"). you -> ready; them -> waiting; a pull
    request (github-pr) -> new."""
    if playbook:
        return "new"
    if owner == "you":
        return "ready"
    return "waiting"


def make_reminder(store, pid: str, now: datetime, loop_id: int, title: str, at: str) -> int:
    """The reminder a loop points at: a task of Odie's for this loop, which rings at `at` as his reminders do."""
    tid = store.add_task(title, "reminder", due_at=at, source_kind="loop", source_ref=f"loop:{loop_id}", origin="agent",
                         personality=pid or None)
    ledger.add_refs(store, loop_id, now, [f"task:{tid}"])
    return tid


def move_reminder(store, loop: dict, at: str) -> bool:
    """Moves a loop's own reminder (one Odie made) to a new time, so it rings again then. False when it has none."""
    task_id = ledger.reminder_of(loop)
    if task_id is None:
        return False
    row = store.one("select status, source_kind, due_at from tasks where id=?", (task_id,))
    if row is None or row["source_kind"] not in ledger.ODIES_TASKS or row["status"] not in ("open", "waiting"):
        return False
    if row["due_at"] != at:
        store.update_task(task_id, due_at=at, delivered_at=None)
    return True


def open_from(store, pid: str, now: datetime, found: dict, answer: dict, done: Applied, after: dict | None) -> int:
    """A new loop from a finding and the model's answer (its title, kind, owner, due, priority win when given)."""
    title = str(answer.get("title") or found["title"]).strip()[:findings.TITLE_MOST]
    kind = str(answer.get("kind") or found["kind"] or "").strip()[:40]
    owner = findings.owner_of(answer.get("owner"), found["owner"])
    due = findings.when_of(answer.get("due")) or found["due"]
    priority = str(answer.get("priority") or "").strip().lower()
    if priority not in ledger.PRIORITIES:
        priority = "normal"
        if found["push"]:
            priority = "high"
    good = [r for r in found["refs"] if github.parse(r) is not None]
    playbook = ""
    book = playbooks.for_kind(kind)
    if book is not None and good:  # a playbook needs a name it can look up
        playbook = book.name
        owner = "odie"
    fact = evidence_of(found)
    if after is not None:
        fact = f"New since you finished #{after['id']} ({after['title'][:60]}): {answer.get('why') or fact}"
    lid = ledger.open_loop(store, pid, now, title, kind, owner=owner, refs=found["refs"], priority=priority,
                           due_at=due, playbook=playbook, state=state_for(owner, playbook), source=source_of(found),
                           ref=found["ref"], fact=fact, card=found["card"], result=found["why"])
    if found["remind_at"]:
        make_reminder(store, pid, now, lid, title, found["remind_at"])
        done.reminders += 1
    done.opened.append(lid)
    if found["push"] and owner == "you":
        done.to_push.append(lid)
    return lid


def add_to(store, now: datetime, loop: dict, found: dict, answer: dict, done: Applied) -> None:
    """A finding that is the same as an open loop: its evidence (once per source item), its refs and card fields; the
    model's new due, owner, title or priority; his move becomes a card; its reminder moved, or made when it has none."""
    lid = loop["id"]
    already = {e["ref"] for e in ledger.events(store, lid) if e["ref"]}
    if found["ref"] and found["ref"] in already:
        ledger.add_refs(store, lid, now, found["refs"])
    else:
        ledger.attach(store, lid, now, source_of(found), found["ref"], evidence_of(found), refs=found["refs"])
    fields: dict = {}
    due = findings.when_of(answer.get("due")) or found["due"]
    if due and due != loop["due_at"]:
        fields["due_at"] = due
    owner = findings.owner_of(answer.get("owner"), loop["owner"])
    if loop["playbook"]:
        owner = loop["owner"]  # a pull request stays Odie's to follow
    if owner != loop["owner"]:
        fields["owner"] = owner
    if answer.get("title"):
        fields["title"] = str(answer["title"]).strip()[:findings.TITLE_MOST]
    if found["why"]:
        fields["result"] = found["why"]
    became_ready = owner == "you" and loop["state"] == "waiting" and not loop["playbook"]
    if became_ready:
        fields["state"] = "ready"
        fields["shown_at"] = now.isoformat(timespec="seconds")
    if fields:
        ledger.update(store, lid, now, **fields)
    ledger.merge_card(store, lid, now, found["card"])
    if found["remind_at"] and not move_reminder(store, loop, found["remind_at"]):
        make_reminder(store, loop["personality"], now, lid, fields.get("title") or loop["title"], found["remind_at"])
        done.reminders += 1
    done.changed.append(lid)
    if found["push"] and became_ready:
        done.to_push.append(lid)


def attach_quietly(store, now: datetime, loop: dict, found: dict, done: Applied) -> None:
    """News about a loop that is closed (he said Done, or Odie closed it): kept as evidence, nothing else. No news,
    no card, no reminder, no push."""
    already = {e["ref"] for e in ledger.events(store, loop["id"]) if e["ref"]}
    if not found["ref"] or found["ref"] not in already:
        ledger.attach(store, loop["id"], now, source_of(found), found["ref"], evidence_of(found), refs=found["refs"],
                      news=False)
    done.quiet.append(loop["id"])
    if found["remind_at"]:
        done.reminder_to_finished = True


def close_from(store, now: datetime, loop: dict, found: dict, answer: dict, done: Applied) -> None:
    """A finding that shows an open loop is finished: its evidence first, then the close citing it."""
    add_to(store, now, loop, {**found, "remind_at": None, "push": False}, {}, Applied())
    why = str(answer.get("why") or found["done"] or evidence_of(found)).strip()
    ledger.close(store, loop["id"], now, "odie", why)
    done.closed.append(loop["id"])


def mine(store, pid: str, value) -> dict | None:
    """The loop a number names, when it is this owner's; None for another's, a missing one or no number."""
    n = number(value)
    if n is None:
        return None
    loop = ledger.get(store, n)
    if loop is None or loop["personality"] != pid:
        return None
    return loop


def verdict_for(store, pid: str, found: dict, answer: dict | None, hint: dict) -> tuple[str, dict | None, dict]:
    """What code does with one finding, from the model's answer and the shortcut's hint, with the rails (this
    module's notes). Returns (what, the loop it is about or None, the answer to use):
      "same"/"closes" an open loop of his -> ("add" / "close", that loop)
      "same" or "closes" a closed loop -> ("quiet", that loop)
      "new" while a finished loop holds its own ID, no "after" -> ("quiet", the finished loop)
      "new" with "after": N (a finished loop) -> ("new", that finished loop)  (a new ask, said so in its Why)
      "new" while an open loop holds its pull request -> ("add", that loop)
      "nothing" -> ("skip", None), but never for a pull request or issue (stage 4 reads GitHub and decides; as no
      answer);  "same" as his own task -> ("skip", None)
      no answer, or a loop that isn't his -> by the hint: open -> add (close, when the finding says it's done),
      finished -> quiet; else ("new", None)"""
    answer = answer or {}
    verdict = answer.get("is", "")
    names_a_pr = any(github.parse(r) is not None for r in found["refs"])
    if verdict == "nothing" and names_a_pr:
        verdict = ""  # a pull request is the playbook's to judge from GitHub's facts (stage 4), never dropped here
        answer = {}
    if verdict == "nothing":
        return "skip", None, answer
    if verdict == "same" and number(answer.get("task")) is not None and not answer.get("loop"):
        return "skip", None, answer
    if verdict in ("same", "closes"):
        loop = mine(store, pid, answer.get("loop"))
        if loop is not None and loop["state"] not in ledger.OPEN:
            return "quiet", loop, answer
        if loop is not None:
            if verdict == "closes":
                return "close", loop, answer
            return "add", loop, answer
    if verdict == "new":
        after = mine(store, pid, answer.get("after"))
        if after is not None and after["state"] not in ledger.OPEN:
            return "new", after, answer
        if "finished" in hint:
            return "quiet", ledger.get(store, hint["finished"]), answer
        same_pr = ledger.find_by_refs(store, pid, [r for r in found["refs"] if github.parse(r) is not None])
        if same_pr is not None:  # looked up now: an earlier finding of this check may have opened it
            return "add", same_pr, answer
        return "new", None, answer
    if "open" in hint and found["done"]:
        return "close", ledger.get(store, hint["open"]), {}  # its own ID ties it, and the check saw it finished
    if "open" in hint:
        return "add", ledger.get(store, hint["open"]), {}
    if "finished" in hint:
        return "quiet", ledger.get(store, hint["finished"]), {}
    return "new", None, {}


def apply(store, pid: str, now: datetime, found: list[dict], answers: dict[str, dict], shortcut: dict[str, dict]) -> Applied:
    """Writes stage 2's answers to the ledger (verdict_for decides each). A finding "same as F1" goes where F1 went."""
    done = Applied()
    for f in found:
        answer = answers.get(f["id"]) or {}
        same_as = str(answer.get("finding") or shortcut.get(f["id"], {}).get("finding") or "")
        if answer.get("is") in ("same", None, "") and not answer.get("loop") and same_as in done.placed:
            target = ledger.get(store, done.placed[same_as])
            if target["state"] in ledger.OPEN:
                add_to(store, now, target, f, answer, done)
            else:
                attach_quietly(store, now, target, f, done)
            done.placed[f["id"]] = target["id"]
            continue
        what, loop, used = verdict_for(store, pid, f, answer or None, shortcut.get(f["id"], {}))
        if what == "skip":
            continue
        if what == "add" and loop is not None:
            add_to(store, now, loop, f, used, done)
        elif what == "close" and loop is not None:
            close_from(store, now, loop, f, used, done)
        elif what == "quiet" and loop is not None:
            attach_quietly(store, now, loop, f, done)
        else:
            after = None
            if what == "new" and loop is not None:
                after = loop
            loop = {"id": open_from(store, pid, now, f, used, done, after)}
        done.placed[f["id"]] = loop["id"]
    return done


def pending_key(pid: str) -> str:
    from odie.watch.owner import key
    return key(PENDING, pid)


def take_pending(store, pid: str) -> tuple[list[dict], int]:
    """The findings a failed stage 2 left for this check, and how many checks they have waited."""
    saved = store.get_setting(pending_key(pid)) or {}
    return list(saved.get("findings") or []), int(saved.get("tries") or 0)


def renumber(found: list[dict]) -> list[dict]:
    for n, f in enumerate(found, start=1):
        f["id"] = f"F{n}"
    return found


async def consolidate(store, pid: str, now: datetime, found: list[dict], think, context: dict) -> Applied | None:
    """Stage 2 for one check's findings (with any left pending by a failed one). think(prompt, instruction) is the
    model call with no tools, on the owner's brain. Returns what was done, or None when the findings wait (pending)."""
    waiting, tries = take_pending(store, pid)
    found = renumber([*waiting, *found])
    if not found:
        return Applied()
    shortcut = hints(store, pid, found)
    prompt = prompt_for(store, pid, now, found, shortcut, context)
    answers = None
    for attempt in range(2):  # asked once more when the answer can't be read
        budget.count(store, now)
        ask = prompt
        if attempt:
            ask += "\n\nYour last answer couldn't be read. Answer with the JSON only, one answer per finding."
        try:
            answers = parse(await think(ask, instruction()))
        except Exception:  # noqa: BLE001 (a failed call: asked again, then the findings wait)
            log.warning("consolidate: the model call failed", exc_info=True)
            answers = None
        if answers is not None:
            break
    if answers is None and tries + 1 < PENDING_TRIES:
        store.set_setting(pending_key(pid), {"findings": found, "tries": tries + 1})
        return None
    store.set_setting(pending_key(pid), {})
    return apply(store, pid, now, found, answers or {}, shortcut)
