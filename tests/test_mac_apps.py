"""The four app modules with a fake runner: arguments as the scripts expect them, JSON back as records, and the
checks each does before running anything."""
from datetime import datetime

import pytest

from odie.mac import calendar, contacts, mail, reminders, scripts


def runner(answer: str):
    calls = []

    async def run(name, *args, app="", timeout=60):
        calls.append((name, args, app))
        return answer
    return run, calls


async def test_new_mail_asks_since_a_time_and_returns_the_records():
    run, calls = runner('[{"id": "mac:12", "from": "Axis <cc@axis.bank.in>", "subject": "Statement", "at": "2026-10-21T13:47:36+05:30", "snippet": "Dear", "attachments": [{"name": "stmt.pdf", "size": 120}]}]')
    got = await mail.new_mail(datetime(2026, 10, 21, 9, 0), limit=25, run=run)
    assert got[0]["id"] == "mac:12" and got[0]["attachments"][0]["name"] == "stmt.pdf"
    assert calls == [("mail_new", ("2026-10-21T09:00:00", "25"), "Mail")]


async def test_read_and_save_take_only_mails_ids_and_file_names(tmp_path):
    run, calls = runner('{"id": "mac:12", "from": "a", "subject": "s", "at": "2026-10-21T13:47:36+05:30", "body": "Hello", "attachments": []}')
    assert (await mail.read("mac:12", run=run))["body"] == "Hello"
    assert calls[0] == ("mail_read", ("mac:12", "6000"), "Mail")
    with pytest.raises(scripts.MacError):
        await mail.read("gmail:abc", run=run)
    with pytest.raises(scripts.MacError):
        await mail.save_attachment("mac:12", "../x.pdf", tmp_path, run=run)
    saved, calls2 = runner(f'{{"path": "{tmp_path.resolve()}/bill.pdf"}}')
    path = await mail.save_attachment("mac:12", "bill.pdf", tmp_path, run=saved)
    assert path == (tmp_path.resolve() / "bill.pdf") and calls2[0][1] == ("mac:12", "bill.pdf", str(tmp_path.resolve()))
    elsewhere, _ = runner('{"path": "/etc/passwd"}')
    with pytest.raises(scripts.MacError):
        await mail.save_attachment("mac:12", "bill.pdf", tmp_path, run=elsewhere)


async def test_calendar_events_and_add():
    run, calls = runner('[{"id": "u1", "title": "Udo birthday", "start": "2026-10-22T00:00:00+05:30", "end": "2026-10-23T00:00:00+05:30", "where": "", "attendees": [], "calendar": "Home", "all_day": true}]')
    got = await calendar.events(datetime(2026, 10, 21, 0, 0), datetime(2026, 10, 28, 0, 0), run=run)
    assert got[0]["calendar"] == "Home" and calls[0] == ("calendar_events", ("2026-10-21T00:00:00", "2026-10-28T00:00:00"), "Calendar")
    listing, _ = runner('[{"name": "Home", "writable": true}, {"name": "Work", "writable": false}]')
    assert [c["name"] for c in await calendar.calendars(run=listing)] == ["Home", "Work"]
    made, calls2 = runner('{"id": "u9", "calendar": "Home"}')
    out = await calendar.add("Pay Axis card", datetime(2026, 10, 29, 9, 0), datetime(2026, 10, 29, 9, 30), where="", notes="₹50,489.55", run=made)
    assert out == {"id": "u9", "calendar": "Home"}
    assert calls2[0][1] == ("Pay Axis card", "2026-10-29T09:00:00", "2026-10-29T09:30:00", "", "", "₹50,489.55")
    with pytest.raises(scripts.MacError):
        await calendar.add("", datetime(2026, 10, 29, 9, 0), datetime(2026, 10, 29, 9, 30), run=made)
    with pytest.raises(scripts.MacError):
        await calendar.add("x", datetime(2026, 10, 29, 9, 30), datetime(2026, 10, 29, 9, 0), run=made)


async def test_reminders_and_contacts():
    run, calls = runner('[{"id": "r1", "title": "Buy medicine", "due": "2026-10-21T20:00:00+05:30", "list": "Reminders"}]')
    assert (await reminders.due(datetime(2026, 10, 22, 0, 0), run=run))[0]["title"] == "Buy medicine"
    assert calls[0] == ("reminders_due", ("2026-10-22T00:00:00",), "Reminders")
    made, calls2 = runner('{"id": "r2", "list": "Reminders"}')
    assert (await reminders.add("Pay the card", datetime(2026, 10, 28, 9, 0), run=made))["id"] == "r2"
    assert calls2[0][1] == ("Pay the card", "2026-10-28T09:00:00", "")
    people, calls3 = runner('[{"name": "Asha Rao", "emails": ["g@x.in"], "phones": [], "birthday": ""}]')
    assert (await contacts.find("Asha", run=people))[0]["emails"] == ["g@x.in"]
    assert calls3[0] == ("contacts_find", ("Asha", "10"), "Contacts")
    with pytest.raises(scripts.MacError):
        await contacts.find("G", run=people)
