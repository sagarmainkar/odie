"""Quiet rules, "Less like this" and "Forget this" (proactive design §8, phase 5): a Quiet rule is written only by his
tap, in plain words he can see and delete; a card of a quieted (or learned) kind is a digest line instead of a card,
and never pushes. Forget this deletes the loop and its evidence."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.loops import cards, ladder, learn, ledger, quiet
from odie.store.db import Store

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def his_card(store, title, kind="newsletter", sender="news@acme.example", pid="", due=None):
    lid = ledger.open_loop(store, pid, NOW, title, kind, owner="you", state="ready", due_at=due,
                           card={"sender": sender} if sender else None, refs=[f"mail:{title[:4]}"],
                           fact="From mail")
    return lid


def test_less_like_this_writes_a_plain_rule_he_can_see_and_delete(store):
    lid = his_card(store, "Acme weekly digest")
    rule = quiet.less_like_this(store, ledger.get(store, lid), NOW)
    assert rule["text"] == 'Fewer "newsletter" cards from news@acme.example: they go in the evening digest'
    assert [r["text"] for r in quiet.rules(store, "")] == [rule["text"]]
    assert learn.taps_of(store, lid) == ["less"]
    assert quiet.delete(store, "", rule["id"]) is True
    assert quiet.rules(store, "") == [] and quiet.delete(store, "", rule["id"]) is False


def test_a_rule_matches_its_kind_and_sender_only(store):
    acme = his_card(store, "Acme weekly digest")
    quiet.less_like_this(store, ledger.get(store, acme), NOW)
    other_sender = his_card(store, "Globex weekly", sender="hello@globex.example")
    other_kind = his_card(store, "Acme invoice", kind="bill")
    again = his_card(store, "Acme weekly digest 2")
    assert quiet.digest_only(store, ledger.get(store, again)) is True
    assert quiet.digest_only(store, ledger.get(store, other_sender)) is False
    assert quiet.digest_only(store, ledger.get(store, other_kind)) is False


def test_a_rule_without_a_sender_quiets_the_kind_and_without_both_the_title(store):
    no_sender = his_card(store, "School circular", kind="notice", sender="")
    rule = quiet.less_like_this(store, ledger.get(store, no_sender), NOW)
    assert rule["text"] == 'Fewer "notice" cards: they go in the evening digest'
    no_kind = his_card(store, "Weekly quiz", kind="", sender="")
    rule2 = quiet.less_like_this(store, ledger.get(store, no_kind), NOW)
    assert rule2["text"] == 'Fewer cards like "Weekly quiz": they go in the evening digest'
    assert quiet.digest_only(store, ledger.get(store, his_card(store, "Weekly quiz", kind="", sender=""))) is True


def test_a_digest_only_card_is_no_card_no_hello_line_and_no_push(store):
    lid = his_card(store, "Acme weekly digest", due=(NOW + timedelta(hours=20)).isoformat())
    keep = his_card(store, "Reply to Asha", kind="reply", sender="asha@example.com")
    quiet.less_like_this(store, ledger.get(store, lid), NOW)
    refs = [c["ref"] for c in cards.cards(store, "", NOW)]
    assert f"loop:{lid}" not in refs and f"loop:{keep}" in refs
    assert [lp["id"] for lp in quiet.digest_lines(store, "", NOW)] == [lid]
    pushed = []
    ladder.run(store, NOW, lambda pid: lambda t, b: pushed.append(t))
    assert pushed == []  # a due-tomorrow push never goes for a digest line
    later = NOW + timedelta(days=3)
    assert all("Acme" not in line for line in ladder.hello_lines(store, "", later))


def test_learned_kinds_are_digest_lines_too(store):
    for n in range(5):
        lid = ledger.open_loop(store, "", NOW - timedelta(days=5), f"Promo {n}", "promo", owner="you", state="ready")
        ledger.update(store, lid, NOW - timedelta(days=4), tapped="later")
    learn.learn(store, "", NOW)
    fresh = ledger.open_loop(store, "", NOW, "Promo 6", "promo", owner="you", state="ready")
    assert quiet.digest_only(store, ledger.get(store, fresh)) is True


def test_pull_requests_are_never_quieted(store):
    lid = ledger.open_loop(store, "", NOW, "app #49", "pull request", refs=["example/app#49"], playbook="github-pr",
                           state="ready")
    with pytest.raises(ValueError):
        quiet.less_like_this(store, ledger.get(store, lid), NOW)


def test_the_watch_never_pushes_a_digest_only_card(store):
    from odie.loops.consolidate import Applied
    from odie.watch import check
    lid = his_card(store, "Acme weekly digest")
    quiet.less_like_this(store, ledger.get(store, lid), NOW)
    again = his_card(store, "Acme weekly digest 2")
    applied = Applied()
    applied.to_push = [again]
    pushed = []
    check.push_new_cards(store, NOW, applied, False, "", lambda t, b: pushed.append(t))
    assert pushed == []


def test_rules_are_each_owners_own(store):
    mira = personalities.create(store, "Mira")
    lid = his_card(store, "Acme weekly digest", pid=mira.id)
    quiet.less_like_this(store, ledger.get(store, lid), NOW)
    assert quiet.rules(store, "") == [] and len(quiet.rules(store, mira.id)) == 1
    mine = his_card(store, "Acme weekly digest 2")
    assert quiet.digest_only(store, ledger.get(store, mine)) is False


def test_a_rule_never_holds_a_secret(store):
    with pytest.raises(ValueError):
        quiet.add(store, "", "newsletter", "", NOW, title="my PIN is 4321")


# --- the review's proposals: a card, the rule only on his tap ---

def test_a_proposal_is_a_card_and_only_his_tap_writes_the_rule(store):
    proposal = quiet.propose(store, "", NOW, "newsletter", "news@acme.example", "you tapped Later on 4 of them")
    assert quiet.rules(store, "") == []
    [card] = quiet.proposal_cards(store, "")
    assert card["ref"] == f"quiet:{proposal['id']}" and card["main"]["action"] == "quiet_accept"
    assert card["other"]["action"] == "dismiss" and "evening digest" in card["title"] + card["why"]
    rule = quiet.accept(store, "", proposal["id"], NOW)
    assert rule["text"].startswith('Fewer "newsletter" cards from news@acme.example')
    assert quiet.proposal_cards(store, "") == [] and quiet.accept(store, "", proposal["id"], NOW) is None


def test_a_proposal_said_no_to_is_gone_and_not_proposed_again(store):
    proposal = quiet.propose(store, "", NOW, "newsletter", "", "rarely read")
    assert quiet.decline(store, "", proposal["id"]) is True
    assert quiet.proposal_cards(store, "") == []
    assert quiet.propose(store, "", NOW, "Newsletter", "", "again") is None  # he said no to this one


def test_a_proposal_like_an_existing_rule_is_not_made(store):
    lid = his_card(store, "Acme weekly digest")
    quiet.less_like_this(store, ledger.get(store, lid), NOW)
    assert quiet.propose(store, "", NOW, "newsletter", "news@acme.example", "x") is None


# --- Forget this ---

def test_forget_deletes_the_loop_its_evidence_and_taps_and_closes_odies_reminder(store):
    from odie.loops.consolidate import make_reminder
    lid = his_card(store, "Acme weekly digest")
    tid = make_reminder(store, "", NOW, lid, "Acme weekly digest", "2026-11-20T09:00:00+05:30")
    ledger.update(store, lid, NOW, tapped="later")
    store.set_setting(f"loops.test:{lid}", {"ok": True})
    ledger.forget(store, lid)
    assert ledger.get(store, lid) is None and ledger.events(store, lid) == []
    assert learn.taps_of(store, lid) == []
    assert store.get_setting(f"loops.test:{lid}") is None
    assert store.one("select status from tasks where id=?", (tid,))["status"] == "done"


def test_card_menu_has_split_less_like_this_and_forget(store):
    lid = his_card(store, "Acme weekly digest")
    [card] = [c for c in cards.cards(store, "", NOW) if c["ref"] == f"loop:{lid}"]
    assert [m["action"] for m in card["more"]] == ["split", "less_like_this", "forget"]
    pr = ledger.open_loop(store, "", NOW, "app #49", "pull request", refs=["example/app#49"], playbook="github-pr",
                          state="ready")
    [pr_card] = [c for c in cards.cards(store, "", NOW) if c["ref"] == f"loop:{pr}"]
    assert [m["action"] for m in pr_card["more"]] == ["split", "forget"]  # a PR is never quieted
