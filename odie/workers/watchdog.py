"""The watchdog: code that reads the jobs store once a minute and asks the router to act. It never touches a job
itself. A running job that ran past its budget, made no call for STALL_MINUTES, or hit the same refusal
SAME_ERROR_TIMES in a row is failed and its chat told. Nothing is retried on its own: a failed job shows Retry, and
the user decides."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from odie.store.db import Store
from odie.workers import store as jobs

log = logging.getLogger("odie.workers")

STALL_MINUTES = 10
BUDGET_GRACE_SECONDS = 120
SAME_ERROR_TIMES = 3


def _at(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def same_error_run(acts: list[dict], times: int = SAME_ERROR_TIMES) -> str | None:
    """The error the last `times` actions all share (refusal or raised), or None. Decides "going round in circles":
    [rm refused, rm refused, rm refused] -> "deletes or stops something"; [ok, refused, refused] -> None."""
    tail = acts[-times:]
    if len(tail) < times:
        return None
    errors = [a.get("refused") or a.get("error") for a in tail]
    if all(errors) and len(set(errors)) == 1:
        return errors[0]
    return None


def why_stuck(row: dict, acts: list[dict], now: datetime) -> str | None:
    """Why a running job should be failed now, or None while it is fine. Worked examples (budget 45 min):
      started 47 minutes ago (past the budget and its grace)  -> "ran past its budget and didn't stop"
      a Worker's last call 12 minutes ago                     -> "made no progress for 10 minutes"
      a Worker's last three calls the same refusal            -> "hit the same refusal 3 times: deletes or stops something"
      a pull request's test, 30 minutes in, no calls          -> None (code runs it; a test suite is quiet)
      started 2 minutes ago, a call 1 minute ago              -> None"""
    started = _at(row.get("started_at"))
    if started and now > started + timedelta(seconds=row["budget_seconds"] + BUDGET_GRACE_SECONDS):
        return "ran past its budget and didn't stop"
    if row.get("kind") == "pr_test":
        return None
    last = started
    if acts:
        last = _at(acts[-1]["ts"])
    if last and now > last + timedelta(minutes=STALL_MINUTES):
        return f"made no progress for {STALL_MINUTES} minutes"
    same = same_error_run(acts)
    if same:
        return f"hit the same refusal {SAME_ERROR_TIMES} times: {same}"
    return None


async def check(store: Store, now: datetime | None = None) -> list[str]:
    """One pass: fail what is stuck. Returns one line per job failed, for the log and tests."""
    from odie.workers import router
    if now is None:
        now = datetime.now(UTC)
    done: list[str] = []
    for row in jobs.running(store):
        if row["status"] != "running":
            continue
        why = why_stuck(row, jobs.actions(store, row["id"]), now)
        if why:
            await router.fail(row["id"], why)
            done.append(f"{row['id']}: failed, {why}")
    for line in done:
        log.warning("watchdog: %s", line)
    return done
