"""The mac-apps skill's tools: thin, typed wrappers over odie.mac.*, each checking the app's permission first and
answering with the Settings line when it isn't granted (never raising macOS's dialog from a chat turn)."""
from __future__ import annotations

from datetime import datetime

from google.adk.tools import FunctionTool

from odie.mac import calendar, contacts, mail, permissions, reminders, scripts

NOT_YET = "Odie isn't allowed to read {app} yet. Allow it in Settings → Mac apps, then ask again."


def _blocked(app_id: str) -> dict | None:
    """The error to answer with when the app's permission isn't granted, else None.
    (mail granted) -> None; (calendar unknown) -> {"error": "Odie isn't allowed to read Calendar yet. …"}"""
    if permissions.status(app_id) == permissions.GRANTED:
        return None
    return {"error": NOT_YET.format(app=permissions.APPS[app_id])}


def _time(text: str) -> datetime:
    """A local ISO time from the model: "2026-10-29T09:00" -> that datetime; "2026-10-29" -> midnight."""
    return datetime.fromisoformat(text.strip())


def _said(e: Exception) -> dict:
    return {"error": str(e)[:300] or type(e).__name__}


async def mac_mail_new(since: str, limit: int = 25) -> dict:
    """New mail in the Mac's Mail app since a local time ("2026-10-21T09:00"), newest first, at most `limit`:
    id, from, subject, at, snippet, attachments. Read one in full with mac_mail_read. This is Apple Mail only: a mail
    that isn't here may be in another connected mail app, so load its skill and look there before saying it isn't
    found. Never search the disk for mail."""
    if blocked := _blocked("mail"):
        return blocked
    try:
        return {"messages": await mail.new_mail(_time(since), limit)}
    except (scripts.MacError, ValueError) as e:
        return _said(e)


async def mac_mail_read(mail_id: str) -> dict:
    """One message from the Mac's Mail app in full, by the id mac_mail_new gave ("mac:123"). An id without "mac:"
    belongs to another mail app: read it with that app's tools."""
    if blocked := _blocked("mail"):
        return blocked
    try:
        return await mail.read(mail_id)
    except scripts.MacError as e:
        return _said(e)


async def mac_mail_save_attachment(mail_id: str, name: str) -> dict:
    """Saves one attachment of a Mail message (by the message's id and the attachment's name) into Odie's workspace;
    returns its path."""
    if blocked := _blocked("mail"):
        return blocked
    from odie.agent.tools.files import workspace
    folder = workspace() / "mail" / mail_id.replace(":", "_")
    try:
        path = await mail.save_attachment(mail_id, name, folder)
    except scripts.MacError as e:
        return _said(e)
    return {"path": str(path), "name": name}


async def mac_calendar_events(start: str, end: str) -> dict:
    """Events in every calendar on this Mac between two local times ("2026-10-21T00:00", "2026-10-28T00:00"):
    id, title, start, end, where, attendees, calendar, all_day."""
    if blocked := _blocked("calendar"):
        return blocked
    try:
        return {"events": await calendar.events(_time(start), _time(end))}
    except (scripts.MacError, ValueError) as e:
        return _said(e)


async def mac_calendar_add(title: str, start: str, end: str, calendar_name: str = "", where: str = "", notes: str = "") -> dict:
    """Adds an event to the Mac's calendar (the first writable one, or `calendar_name`). Local times. Returns the
    event's id and the calendar it went into."""
    if blocked := _blocked("calendar"):
        return blocked
    try:
        return await calendar.add(title, _time(start), _time(end), calendar_name or calendar.chosen(), where, notes)
    except (scripts.MacError, ValueError) as e:
        return _said(e)


async def mac_reminders(before: str) -> dict:
    """Open reminders in the Reminders app due before a local time: id, title, due, list."""
    if blocked := _blocked("reminders"):
        return blocked
    try:
        return {"reminders": await reminders.due(_time(before))}
    except (scripts.MacError, ValueError) as e:
        return _said(e)


async def mac_reminder_add(title: str, due: str, list_name: str = "") -> dict:
    """Adds a reminder to the Reminders app, due at a local time, in the default list or `list_name`."""
    if blocked := _blocked("reminders"):
        return blocked
    try:
        return await reminders.add(title, _time(due), list_name)
    except (scripts.MacError, ValueError) as e:
        return _said(e)


async def mac_contacts(query: str) -> dict:
    """People in the Mac's Contacts whose name holds `query`: name, emails, phones, birthday."""
    if blocked := _blocked("contacts"):
        return blocked
    try:
        return {"people": await contacts.find(query)}
    except scripts.MacError as e:
        return _said(e)


TOOLS = [
    FunctionTool(mac_mail_new), FunctionTool(mac_mail_read), FunctionTool(mac_mail_save_attachment),
    FunctionTool(mac_calendar_events), FunctionTool(mac_calendar_add, require_confirmation=True),
    FunctionTool(mac_reminders), FunctionTool(mac_reminder_add, require_confirmation=True),
    # mac_contacts is held back with Contacts (odie.mac.permissions.HELD_BACK); add it here to offer it again
]
