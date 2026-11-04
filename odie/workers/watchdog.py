"""The watchdog: code that reads the jobs store once a minute and asks the Router to act. It never touches a Worker
itself. A running job that ran past its budget and didn't stop, made no call for STALL_MINUTES, or hit the same error
SAME_ERROR_TIMES in a row is failed and the chat is told; a waiting reporter whose run is overdue is launched again.
Nothing is retried on its own beyond that: a failed job shows a Retry (retry_job), and the user decides."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from odie.store.db import Store
from odie.workers import store as jobs

log = logging.getLogger("odie.workers")

STALL_MINUTES = 10
BUDGET_GRACE_SECONDS = 120
SAME_ERROR_TIMES = 3
MISSED_RUN_GRACE_MINUTES = 5


def _at(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
    """Why a running job should be failed now, or None while it is fine. Worked examples (budget 30 min):
      started 40 minutes ago, still running              -> "ran past its budget and didn't stop"
      last call 12 minutes ago, budget not reached        -> "made no progress for 10 minutes"
      last three calls the same refusal                   -> "hit the same refusal three times: deletes or stops something"
      started 2 minutes ago, a call 1 minute ago          -> None"""
    started = _at(row.get("started_at"))
    if started and now > started + timedelta(seconds=row["budget_seconds"] + BUDGET_GRACE_SECONDS):
        return "ran past its budget and didn't stop"
    last = _at(acts[-1]["ts"]) if acts else started
    if last and now > last + timedelta(minutes=STALL_MINUTES):
        return f"made no progress for {STALL_MINUTES} minutes"
    same = same_error_run(acts)
    if same:
        return f"hit the same refusal {SAME_ERROR_TIMES} times: {same}"
    return None


def missed_run(row: dict, now: datetime) -> bool:
    """A waiting reporter whose next run is overdue by MISSED_RUN_GRACE_MINUTES (its task died, or Odie slept):
    next_run_at 10:00, now 10:07 -> True; now 10:03 -> False; a running job -> False."""
    if row["status"] != "waiting":
        return False
    due = _at(row.get("next_run_at"))
    return bool(due) and now > due + timedelta(minutes=MISSED_RUN_GRACE_MINUTES)


async def check(store: Store, now: datetime | None = None) -> list[str]:
    """One pass: fail what is stuck, launch what was missed. Returns one line per action, for the log and tests."""
    from odie.workers import router
    now = now or datetime.now(UTC)
    done: list[str] = []
    for row in jobs.running(store):
        if row["status"] == "running":
            why = why_stuck(row, jobs.actions(store, row["id"]), now)
            if why:
                await router.fail(row["id"], why)
                done.append(f"{row['id']}: failed, {why}")
        elif missed_run(row, now) and row["id"] not in router.running_ids():
            router.launch(jobs.from_row(row))
            done.append(f"{row['id']}: launched again, its run was missed")
    for line in done:
        log.warning("watchdog: %s", line)
    return done
