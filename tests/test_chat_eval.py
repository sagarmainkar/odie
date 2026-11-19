"""The promise eval's cases (evals/promises/cases) hold the code's part to the score: with the scripted model, every
case is right, so a miss in a live run is the model's."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.loops import chat_eval
from odie.store.db import Store

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
CASES = chat_eval.load_cases()


def test_there_are_cases_for_each_part():
    ids = {c["id"] for c in CASES}
    assert {"build-tonight", "call-the-bank-friday", "quoted-mail-promise", "pasted-mail", "tap-turn-promise",
            "reminder-already-made", "page-tells-odie-to-promise"} <= ids


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_every_case_is_right_with_the_scripted_model(case, isolated_settings, tmp_path):
    store = Store(tmp_path / "a.db")
    store.init_schema()
    result = await chat_eval.run_case(store, case, NOW, chat_eval.scripted(case))
    assert result["score"]["wrong"] == [], result
