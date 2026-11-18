"""What the user sent closes what it answers (18 Nov 2026): every check reads the user's sent mail since the last check;
a sent mail in the same thread as an open reply closes it in code ("you replied 18 Nov 14:20"); the rest go to the
check as "What you sent", for the model to match. What closes shows in Done today, never silently gone."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.store.db import Store
from odie.watch import bills, fetch, needs, report, sent, sources, threads
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


def card_with(store, *items):
    store.set_setting(report.CARD, {"checked_at": "", "line": "", "needs_you": list(items), "events": [], "sources": {}})


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
    threads.track(store, "mail:g1", "reply", "Reply to A Person", "owed", mail_thread="t1", mail_source="mail:gmail-calendar",
                  sender="a.person@example.com")
    card_with(store, {"ref": "mail:g1", "title": "Reply to A Person", "thread": "t1", "pile": "alerts",
                      "sender": "a.person@example.com"})
    left = sent.close_answered(store, AFTERNOON, [mine("s1", "t1"), mine("s2", "t7", subject="Lunch?")])
    assert [m.id for m in left] == ["s2"]  # what closed nothing goes to the check as "What you sent"
    assert threads.open_refs(store) == set()
    assert store.get_setting(report.CARD)["needs_you"] == []
    [closed] = bills.closed_by_watch(store, AFTERNOON - timedelta(days=1))  # Done today, with Reopen
    assert closed["title"] == "Reply to A Person" and closed["why"] == "you replied 18 Nov 14:20"


def test_a_card_item_with_no_thread_followed_closes_too_and_shows_in_done_today(store):
    card_with(store, {"ref": "mail:g2", "title": "Reply to Sam", "thread": "t2", "pile": "personal",
                      "sender": "a.person@example.com"},
              {"ref": "mail:g3", "title": "New sign-in", "thread": "t3", "pile": "alerts"})
    sent.close_answered(store, AFTERNOON, [mine("s1", "t2")])
    assert [i["ref"] for i in store.get_setting(report.CARD)["needs_you"]] == ["mail:g3"]
    notes = needs.recent_notes(store, AFTERNOON)
    assert [n["message"] for n in notes] == ["Reply to Sam: you replied 18 Nov 14:20"]


def test_a_bill_or_an_order_in_the_same_thread_stays_open(store):
    threads.track(store, "mail:b1", "bill", "Gas bill", "due", due="2026-11-25", mail_thread="t5")
    card_with(store, {"ref": "mail:b1", "title": "Gas bill", "thread": "t5", "pile": "bills"})
    left = sent.close_answered(store, AFTERNOON, [mine("s1", "t5")])
    assert [m.id for m in left] == ["s1"]  # a question about a bill doesn't pay it: the model decides
    assert threads.open_refs(store) == {"mail:b1"}
    assert len(store.get_setting(report.CARD)["needs_you"]) == 1


def test_closes_by_its_thread():
    assert sent.closes_by_its_thread("reply") and sent.closes_by_its_thread("alerts")
    assert sent.closes_by_its_thread("personal") and sent.closes_by_its_thread("")
    assert not sent.closes_by_its_thread("bill") and not sent.closes_by_its_thread("bills")
    assert not sent.closes_by_its_thread("order") and not sent.closes_by_its_thread("orders")


def test_a_card_item_keeps_its_mails_thread(store):
    mails = [Mail("g1", "A Person <a.person@example.com>", "Hello", "2026-11-18T08:00:00Z", "hi", [], "mail:gm", thread="t1")]
    report.apply(store, AFTERNOON, [{"ref": "mail:g1", "title": "Reply to A Person"}], "", mails, [], {}, first=True)
    assert store.get_setting(report.CARD)["needs_you"][0]["thread"] == "t1"
    assert store.get_setting(report.CARD)["needs_you"][0]["sender"] == "a.person@example.com"  # a reply must go to them


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
    threads.track(store, "mail:g1", "reply", "Reply to A Person", "owed", mail_thread="t1", mail_source="mail:gmail-calendar",
                  sender="a.person@example.com")
    seen = {}

    async def turn(prompt, tools, instruction):
        seen["open"] = threads.open_refs(store)
        report_tool = next(t for t in tools if t.name == "report")
        await report_tool.run_async(args={"needs_you": [], "line": "quiet"}, tool_context=SimpleNamespace())

    assert await check.run_check(store, day, turn, lambda title, body: None) == "ok"
    assert seen["open"] == set()  # closed in code before the model looked
