"""How well the watch judges mail (22 Oct 2026): made-up mails through the real watch turn, scored.

Each case is a small made-up inbox (`evals/watch/cases/*.json`: one mail; `evals/watch/inboxes/*.json`: 10-15 mails with
the hard ones among promotions) and what the watch should do with each mail: flag it for the user ("needs_you") or not
("not"), and for some, open it before deciding ("must_open": its preview hides what it asks). The watch's real turn
runs on a throwaway home (as odie/blocks_eval.py does), its tools reading from the case through EvalFetcher, and its
report is scored. Nothing is read from Odie's own data except the one API key the provider needs.

Run it with scripts/watch_eval.sh (odie/watch_eval.py: it points Odie at the throwaway home before loading this
module). Results: evals/watch/<date>-<provider>-<model>.json and .md."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from odie.watch.fetch import Fetcher, Mail, address_of, newest_first

REPO = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO / "evals" / "watch"
CASES_DIR = EVAL_DIR / "cases"
INBOXES_DIR = EVAL_DIR / "inboxes"
FREE: frozenset[str] = frozenset()  # no tool runs without its tap in the eval: a mail may ask the assistant to act
TURN_SECONDS = 280  # as the live watch
PROMPT = "Run the watch check."
NUDGE = ("You ended the watch check without calling report. Call report now (an empty needs_you list when nothing "
         "needs the user, and a one-sentence line for Today).")
EVAL_SOURCE = "mail:eval"


def load_cases() -> list[dict]:
    """Every case and inbox, each with its kind ("case" or "inbox") added."""
    out = []
    for kind, folder in (("case", CASES_DIR), ("inbox", INBOXES_DIR)):
        for path in sorted(folder.glob("*.json")):
            case = json.loads(path.read_text())
            case["kind"] = kind
            out.append(case)
    return out


def mail_of(row: dict, body: str | None = None) -> Mail:
    """A case's mail as the watch's Mail: the preview as its body until it is opened."""
    preview = row.get("snippet", "")
    return Mail(id=row["id"], frm=row["from"], subject=row["subject"], at=row.get("at") or row.get("date", ""),
                snippet=preview, attachments=[], source=EVAL_SOURCE, body=body if body is not None else preview,
                sources=[EVAL_SOURCE], thread=row.get("thread", ""))


class EvalFetcher(Fetcher):
    """The watch's reads answered from one case, with every mail it opened kept in `opened`. Nothing is called and
    nothing is saved."""

    def __init__(self, store, now: datetime, case: dict):
        super().__init__(store, now)
        self.case = case
        self.opened: set[str] = set()
        self._bodies = {row["id"]: row.get("body", "") for row in case["mails"]}
        for row in case["mails"]:
            self._mail[row["id"]] = mail_of(row)

    async def new_mail(self) -> list[Mail]:
        return newest_first(list(self._mail.values()))

    async def upcoming_events(self, hours: int = 24) -> list:
        return []

    async def events_ahead(self, days: int) -> list:
        return []

    async def open_mail(self, mail_id: str) -> Mail | None:
        mail = self._mail.get(mail_id)
        if mail is None:
            return None
        self.opened.add(mail_id)
        if mail_id in self._bodies:
            mail.body = self._bodies[mail_id]
            mail.opened = True
        return mail

    async def read_thread(self, mail_id: str) -> list[dict] | str:
        mail = self._mail.get(mail_id)
        if mail is None:
            return "No message with that id in this check: call new_mail first."
        rows = self.case.get("threads", {}).get(mail.thread)
        if rows is None:
            return "This mail has no earlier messages."
        return [{"from": r["from"], "at": r.get("date", ""), "body": r.get("body", "")} for r in rows]

    async def search_mail(self, query: str, limit: int = 10) -> list[Mail] | str:
        rows = self.case.get("search", {}).get(query, [])
        return [mail_of(r) for r in rows][:limit]

    async def sent_to(self, address: str, limit: int = 5) -> list[Mail] | str:
        rows = self.case.get("sent", {}).get(address_of(address), [])
        return [mail_of(r) for r in rows][:limit]

    def commit(self, turn_failed: bool = False) -> None:
        return None


def score(case: dict, report: dict | None, opened: set[str]) -> dict:
    """One case's result against what it expects. Flagged = the report's needs_you names the mail.
    Example: expect m1 needs_you (must_open), m2 not; report flags m1, m1 was opened -> right 2 of 2, opened 1 of 1;
    the report flags m2 and nothing was opened -> right 0, missed [m1], false_alarms [m2], not_opened [m1]."""
    flagged = set()
    for item in (report or {}).get("needs_you", []):
        ref = str(item.get("ref") or "")
        if ref.startswith("mail:"):
            flagged.add(ref[len("mail:"):])
    right, missed, false_alarms, not_opened = 0, [], [], []
    must_open = opened_when_needed = 0
    for mail_id, expect in case["expect"].items():
        wanted = expect["outcome"] == "needs_you"
        if (mail_id in flagged) == wanted:
            right += 1
        elif wanted:
            missed.append(mail_id)
        else:
            false_alarms.append(mail_id)
        if expect.get("must_open"):
            must_open += 1
            if mail_id in opened:
                opened_when_needed += 1
            else:
                not_opened.append(mail_id)
    return {"right": right, "of": len(case["expect"]), "missed": missed, "false_alarms": false_alarms,
            "must_open": must_open, "opened_when_needed": opened_when_needed, "not_opened": not_opened,
            "no_report": report is None}


async def run_case(runner, store, case: dict, now: datetime) -> dict:
    """One case through the real watch turn: its tools read from the case; the report is scored."""
    from odie.watch import check as watch_check
    from odie.watch.tools import Check, watch_tools
    store.execute("delete from tasks")  # each case starts with only its own open reminders
    for title in case.get("open_tasks", []):
        store.add_task(title, "reminder", origin="agent")
    check = Check(EvalFetcher(store, now, case))
    tools = watch_tools(check)
    instruction = watch_check._instruction("", case.get("watch_for", ""))
    started = time.monotonic()
    error = ""
    try:
        await runner.background_turn(PROMPT, timeout=TURN_SECONDS, tools=tools, instruction=instruction,
                                     guard=watch_check.guard, free=FREE)
        if check.report is None:
            await runner.background_turn(NUDGE, timeout=TURN_SECONDS, tools=tools, instruction=instruction,
                                         guard=watch_check.guard, free=FREE)
    except Exception as e:  # noqa: BLE001 (a failed case is recorded, the rest still run)
        error = f"{type(e).__name__}: {e}"[:200]
    fetcher = check.fetcher
    return {"id": case["id"], "kind": case["kind"], "seconds": round(time.monotonic() - started, 1), "error": error,
            "report": check.report, "opened": sorted(fetcher.opened),
            "score": score(case, check.report, fetcher.opened)}


def totals(results: list[dict]) -> dict:
    """Every case's score added up: mails judged right, must-open mails opened, and the lists of what went wrong."""
    out = {"right": 0, "of": 0, "must_open": 0, "opened_when_needed": 0, "missed": [], "false_alarms": [],
           "not_opened": [], "no_report": []}
    for r in results:
        s = r["score"]
        for key in ("right", "of", "must_open", "opened_when_needed"):
            out[key] += s[key]
        for key in ("missed", "false_alarms", "not_opened"):
            out[key] += [f"{r['id']}/{m}" for m in s[key]]
        if s["no_report"]:
            out["no_report"].append(r["id"])
    return out


def run_markdown(run: dict) -> str:
    t = run["totals"]
    lines = [f"# Watch eval: {run['provider']}/{run['model']} ({run['date']}, odie {run['odie_commit']})", "",
             f"- Judged right: **{t['right']} of {t['of']}** mails",
             f"- Opened when its preview hid the ask: **{t['opened_when_needed']} of {t['must_open']}**",
             f"- Missed: {', '.join(t['missed']) or 'none'}",
             f"- False alarms: {', '.join(t['false_alarms']) or 'none'}",
             f"- Not opened: {', '.join(t['not_opened']) or 'none'}",
             f"- No report: {', '.join(t['no_report']) or 'none'}", "", "| case | right | opened | seconds | error |",
             "|---|---|---|---|---|"]
    for r in run["results"]:
        s = r["score"]
        lines.append(f"| {r['id']} | {s['right']}/{s['of']} | {s['opened_when_needed']}/{s['must_open']} | "
                     f"{r['seconds']} | {r['error']} |")
    return "\n".join(lines) + "\n"


async def run_all(provider: str, model: str, cases: list[dict]) -> list[dict]:
    """Every case through a real OdieRunner set to this model. Call only after the throwaway environment is set."""
    from zoneinfo import ZoneInfo

    from odie import config
    from odie.app.runner import OdieRunner
    from odie.models import all_providers
    from odie.store.db import Store

    store = Store(config.settings.db_path)
    store.init_schema()
    known = [p.id for p in all_providers(store)]
    if provider not in known:
        raise SystemExit(f"No provider {provider!r} here (known: {', '.join(known)}). Is its key in Odie's .env?")
    store.set_setting("model.chat", {"provider": provider, "model": model})
    runner = OdieRunner(store)
    runner.review_every = 10**6
    await runner.load_plugins()
    now = datetime(2026, 10, 22, 9, 0, tzinfo=ZoneInfo(config.settings.timezone))
    results = []
    try:
        for case in cases:
            print(f"  {case['id']}: ", end="", flush=True)
            r = await run_case(runner, store, case, now)
            s = r["score"]
            print(f"{s['right']}/{s['of']} right, opened {s['opened_when_needed']}/{s['must_open']}, {r['seconds']} s"
                  f"{', ' + r['error'] if r['error'] else ''}", flush=True)
            results.append(r)
    finally:
        await runner.close()
    return results
