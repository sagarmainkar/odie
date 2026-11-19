"""The Now list (proactive design §5, §15-16 Q5, §17): a short list of what matters to him now, one per owner,
written only by his tap; stage 2 and stage 4 read it; Odie drafts the first one and proposes changes weekly."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.loops import consolidate, now as now_list
from odie.store.db import Store

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_a_new_owner_has_no_now_list(store):
    assert now_list.lines(store, "") == []
    assert now_list.text(store, "") == ""


def test_his_lines_are_kept_cleaned_and_in_his_order(store):
    now_list.save(store, "", ["  Ship Odie 0.3.1 ", "", "Asha's deck by Friday", "Renew the passport"], NOW)
    assert now_list.lines(store, "") == ["Ship Odie 0.3.1", "Asha's deck by Friday", "Renew the passport"]
    assert now_list.text(store, "") == "- Ship Odie 0.3.1\n- Asha's deck by Friday\n- Renew the passport"


def test_each_owner_keeps_its_own(store):
    mira = personalities.create(store, "Mira")
    now_list.save(store, "", ["Ship Odie"], NOW)
    now_list.save(store, mira.id, ["Marathon training"], NOW)
    assert now_list.lines(store, "") == ["Ship Odie"]
    assert now_list.lines(store, mira.id) == ["Marathon training"]


def test_at_most_seven_lines_of_at_most_120_characters(store):
    with pytest.raises(ValueError):
        now_list.save(store, "", [f"line {n}" for n in range(8)], NOW)
    with pytest.raises(ValueError):
        now_list.save(store, "", ["x" * 121], NOW)


def test_a_secret_is_never_kept(store):
    with pytest.raises(ValueError):
        now_list.save(store, "", ["Pay rent from account 123456789012 IFSC HDFC0001234"], NOW)
    with pytest.raises(ValueError):
        now_list.save(store, "", ["Rotate the key sk-abcdefghijklmnopqrstuvwxyz123456"], NOW)
    assert now_list.lines(store, "") == []


def test_stage_2_reads_the_owners_now_list(store):
    now_list.save(store, "", ["Asha's deck by Friday"], NOW)
    found = [{"id": "F1", "ref": "mail:m1", "refs": ["mail:m1"], "title": "Send the deck", "kind": "reply owed",
              "why": "", "owner": "you", "due": None, "done": "", "remind_at": None, "push": False, "card": {},
              "stage": ""}]
    context = {"watch": "", "now": now_list.text(store, ""), "memory": ""}
    prompt = consolidate.prompt_for(store, "", NOW, found, {}, context)
    assert "Now:\n- Asha's deck by Friday" in prompt


async def test_the_watch_hands_stage_2_the_now_list_from_the_store(store, monkeypatch):
    from odie.watch import check
    now_list.save(store, "", ["Asha's deck by Friday"], NOW)
    assert check.context_for(store, "", None, "")["now"] == "- Asha's deck by Friday"


def test_stage_4_reads_the_now_list(store):
    from odie.loops import choose, ledger
    lid = ledger.open_loop(store, "", NOW, "app #49 Threads", "pull request", refs=["example/app#49"],
                           playbook="github-pr")
    loop = ledger.get(store, lid)
    prompt = choose.prompt_for(loop, [], {"state": "open"}, now_text="- Ship Odie 0.3.1")
    assert "What matters to the user now (his Now list):\n- Ship Odie 0.3.1" in prompt
    assert "Now list" not in choose.prompt_for(loop, [], {"state": "open"})
