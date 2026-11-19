"""What the user sent closes what it answers (18 Nov 2026): every check reads the user's sent mail since the last check;
a sent mail in the same thread as an open loop's mail, to its sender, closes it in code ("you replied 18 Nov 14:20");
the rest go to the check as "What you sent", for the model to match. What closes shows in Done today (loops Odie
closed, each with Reopen), never silently gone."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.store.db import Store
from odie.loops import ledger
from odie.watch import fetch, sent, sources
from odie.watch.fetch import Mail
from tests.test_watch_calls import spec_for
from tests.test_watch_fetch import GM_INVITE, NOW, calls_to

IST = ZoneInfo("Asia/Kolkata")
AFTERNOON = datetime(2026, 11, 18, 15, 0, tzinfo=IST)


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def mine(mail_id: str, thread: str, to: str = "A Person <a.person@example.com>", subject: str = "Re: Hello") -> Mail:
    """A mail the user sent at 08:50 UTC on 18 Nov (14:20 in India)."""
    return Mail(mail_id, "Me <me@example.com>", subject, "2026-11-18T08:50:00Z", "Happy to help, Tuesday works.", [],
                "mail:gmail-calendar", thread=thread, to=to)


def a_loop(store, title, thread, sender="a.person@example.com", kind="reply owed", pile="alerts", ref="mail:g1"):
    """A loop from a mail in that thread, as stage 2 makes it (its card keeps the thread and the sender)."""
    return ledger.open_loop(store, "", AFTERNOON - timedelta(days=1), title, kind, owner="you",
                            refs=[ref, f"thread:{thread}"], state="ready",
                            card={"thread": thread, "sender": sender, "pile": pile})


def test_a_sent_mail_says_who_it_went_to():
    text = json.dumps({"messages": [{"id": "s1", "threadId": "t1", "to": "Asha <asha@example.com>", "subject": "Re: x"}]})
    [m] = fetch.parse_mail(text, "mail:g")
    assert (m.to, m.thread) == ("Asha <asha@example.com>", "t1")


async def test_each_check_reads_what_the_user_sent_since_the_last_check(store, tmp_path):
    from odie.plugins import mcp
    since = int((NOW - timedelta(hours=24)).timestamp())  # a first check looks back a day, as for new mail
    sent_by_me = [{"id": "s1", "threadId": "t1", "from": "Me <me@example.com>", "to": "A Person <a.person@example.com>",
                   "subject": "Re: New consultation", "date": "2026-10-08T08:50:00Z", "snippet": "Tuesday works."}]
    mcp.write_config({"gmail-calendar": spec_for("gmailmcp", tmp_path, mail=GM_INVITE,
                                                 query_hits={f"in:sent after:{since}": sent_by_me})})
    await sources.detect_and_save(store)
    got = await fetch.Fetcher(store, NOW).sent_mail()
    assert [m.id for m in got] == ["s1"] and got[0].to == "A Person <a.person@example.com>"
    assert calls_to(tmp_path, "gmail_search")[-1]["query"] == f"in:sent after:{since}"


async def test_apple_mail_and_apps_that_arent_gmail_are_not_asked_for_sent_mail(store):
    from odie.watch.sources import KEY, Source
    apple = Source("mail", "mac", "Apple Mail", "native", "mac_mail_new", {})
    outlook = Source("mail", "outlook", "Outlook", "plain", "search_emails", {}, query_param="query")
    store.set_setting(KEY, {"sources": [apple.as_dict(), outlook.as_dict()]})
    assert await fetch.Fetcher(store, NOW).sent_mail() == []  # nothing called: Apple Mail's tools read only the inbox


def test_reads_sent_mail_only_from_gmail_style_apps():
    from odie.watch.sources import Source
    assert fetch.reads_sent_mail(Source("mail", "gmail-calendar", "Gmail and Calendar", "plain", "gmail_search", {},
                                        query_param="query"))
    assert not fetch.reads_sent_mail(Source("mail", "mac", "Apple Mail", "native", "mac_mail_new", {}))
    assert not fetch.reads_sent_mail(Source("mail", "outlook", "Outlook", "plain", "search_emails", {}, query_param="query"))


def test_a_reply_in_the_same_thread_closes_the_reply_owed_in_code(store):
    lid = a_loop(store, "Reply to A Person", "t1")
    left = sent.close_answered(store, AFTERNOON, [mine("s1", "t1"), mine("s2", "t7", subject="Lunch?")])
    assert [m.id for m in left] == ["s2"]  # what closed nothing goes to the check as "What you sent"
    loop = ledger.get(store, lid)
    assert loop["state"] == "closed" and loop["closed_by"] == "odie" and loop["closed_why"] == "you replied 18 Nov 14:20"
    from odie.loops import cards
    [done] = cards.done_today(store, "", AFTERNOON)  # Done today, with Reopen
    assert done["title"] == "Reply to A Person" and any(e["ref"] == "mail:s1" for e in ledger.events(store, lid))


def test_a_reply_to_someone_else_or_a_loop_from_no_mail_stays_open(store):
    forward = a_loop(store, "Reply to Sam", "t2", sender="sam@example.com")
    plain = ledger.open_loop(store, "", AFTERNOON, "Renew passport", "deadline", owner="you", state="ready")
    left = sent.close_answered(store, AFTERNOON, [mine("s1", "t2")])
    assert [m.id for m in left] == ["s1"]
    assert ledger.get(store, forward)["state"] == "ready" and ledger.get(store, plain)["state"] == "ready"


def test_a_bill_or_an_order_in_the_same_thread_stays_open(store):
    bill = a_loop(store, "Gas bill", "t5", kind="bill", pile="bills", ref="mail:b1")
    order = ledger.open_loop(store, "", AFTERNOON, "Order: lamp", "order delivery", owner="them",
                             refs=["mail:o1", "thread:t6"], state="waiting", card={"thread": "t6",
                                                                                   "sender": "a.person@example.com"})
    left = sent.close_answered(store, AFTERNOON, [mine("s1", "t5"), mine("s2", "t6")])
    assert [m.id for m in left] == ["s1", "s2"]  # a question about a bill doesn't pay it: the model decides
    assert ledger.get(store, bill)["state"] == "ready" and ledger.get(store, order)["state"] == "waiting"


def test_closes_by_its_thread():
    assert sent.closes_by_its_thread("reply") and sent.closes_by_its_thread("alerts")
    assert sent.closes_by_its_thread("personal") and sent.closes_by_its_thread("")
    assert not sent.closes_by_its_thread("bill") and not sent.closes_by_its_thread("bills")
    assert not sent.closes_by_its_thread("order") and not sent.closes_by_its_thread("orders")


async def test_the_check_reads_what_you_sent_and_that_counts_as_reading_mail(store):
    from odie.watch.tools import READ_MAIL, Check, watch_tools
    check = Check(fetch.Fetcher(store, NOW))
    check.sent = [mine("s2", "t7", subject="Lunch on Friday?")]
    what = next(t for t in watch_tools(check) if t.name == "what_you_sent")
    context = SimpleNamespace(state={})
    got = await what.run_async(args={}, tool_context=context)
    listed = json.loads(got["result"])
    assert "Lunch on Friday?" in listed[0]["subject"] and "UNTRUSTED" in listed[0]["subject"]
    assert "a.person@example.com" in listed[0]["to"]
    assert context.state[READ_MAIL] is True  # no reaching the web after this, as after new_mail


async def test_a_check_closes_a_reply_the_user_sent_before_the_model_runs(store, tmp_path):
    from odie.plugins import mcp
    from odie.watch import check
    day = datetime(2026, 10, 8, 10, 0, tzinfo=IST)
    since = int((day - timedelta(hours=24)).timestamp())
    sent_by_me = [{"id": "s1", "threadId": "t1", "from": "Me <me@example.com>", "to": "a.person@example.com",
                   "subject": "Re: New consultation", "date": "2026-10-08T04:00:00Z", "snippet": "Tuesday works."}]
    mcp.write_config({"gmail-calendar": spec_for("gmailmcp", tmp_path, mail=GM_INVITE,
                                                 query_hits={f"in:sent after:{since}": sent_by_me})})
    lid = ledger.open_loop(store, "", day, "Reply to A Person", "reply owed", owner="you", refs=["mail:g1", "thread:t1"],
                           state="ready", card={"thread": "t1", "sender": "a.person@example.com"})
    seen = {}

    async def turn(prompt, tools, instruction):
        seen["open"] = [lp["id"] for lp in ledger.open_loops(store, "")]
        report_tool = next(t for t in tools if t.name == "report")
        await report_tool.run_async(args={"needs_you": [], "line": "quiet"}, tool_context=SimpleNamespace())

    assert await check.run_check(store, day, turn, lambda title, body: None) == "ok"
    assert seen["open"] == [] and ledger.get(store, lid)["closed_by"] == "odie"  # closed in code before the model looked
