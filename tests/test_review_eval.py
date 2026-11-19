"""The evening review's eval cases (evals/review/cases) are right with the scripted model, and the eval can't reach
anything: the review's call has no tools, and the scripted answer goes through the same rails as the real one."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.loops import review_eval
from odie.store.db import Store

NOW = datetime(2026, 11, 19, 19, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
CASES = review_eval.load_cases()


def test_there_are_cases_for_each_judgment():
    ids = {c["id"] for c in CASES}
    assert {"merge-deck-and-call", "two-bills-stay-two", "stale-order", "injected-title"} <= ids


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_every_case_is_right_with_the_scripted_model(case, isolated_settings, tmp_path):
    store = Store(tmp_path / "a.db")
    store.init_schema()
    got = await review_eval.run_case(store, case, NOW)
    assert got["score"]["wrong"] == [], got


async def test_a_wrong_answer_scores_wrong(isolated_settings, tmp_path):
    store = Store(tmp_path / "a.db")
    store.init_schema()
    [case] = [c for c in CASES if c["id"] == "merge-deck-and-call"]
    got = await review_eval.run_case(store, {**case, "script": {"digest": "x"}}, NOW)
    assert got["score"]["wrong"] == ["merged deck+call"]
