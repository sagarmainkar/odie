"""A fake mail and calendar app over stdio, shaped like Zapier, Composio or a plain MCP server (mode in argv[1]).
Data comes from the JSON file in MAIL_DATA; each call is appended to MAIL_LOG (to check what was called)."""
import base64
import json
import os
import sys

from mcp.server.mcpserver import MCPServer

MODE = sys.argv[1]
DATA = json.loads(open(os.environ["MAIL_DATA"]).read())
s = MCPServer("mail")


def _log(name: str, args: dict) -> None:
    if os.environ.get("MAIL_LOG"):
        with open(os.environ["MAIL_LOG"], "a") as f:
            f.write(json.dumps({"tool": name, "args": args}) + "\n")


if MODE == "zapier":
    APPS = {"apps": [{"app": "Gmail", "selected_api": "GoogleMailV2CLIAPI", "action_count": 3},
                     {"app": "Google Calendar", "selected_api": "GoogleCalendarCLIAPI", "action_count": 1}]}
    ACTIONS = {
        "GoogleMailV2CLIAPI": [
            {"key": "message", "name": "Send Email", "action_type": "write", "tool_name": "gmail_send_email"},
            {"key": "message", "name": "Find Email", "action_type": "search", "tool_name": "gmail_find_email",
             "params": [{"key": "query", "required": True}]},
            {"key": "attachment", "name": "Get Attachment by Filename", "action_type": "search",
             "tool_name": "gmail_get_attachment_by_filename",
             "params": [{"key": "message_id", "required": True}, {"key": "attachment_filename", "required": True}]}],
        "GoogleCalendarCLIAPI": [
            {"key": "find_calendars", "name": "Find Calendars", "action_type": "search", "tool_name": "google_calendar_find_calendars"},
            {"key": "event_v2", "name": "Find Events", "action_type": "search", "tool_name": "google_calendar_find_events",
             "params": [{"key": "end_time"}, {"key": "calendarid", "required": True}, {"key": "start_time"}]}],
    }

    @s.tool()
    def inspect_zapier_actions(selected_api: str = "", tool_name: str = "") -> str:
        """List the apps and actions."""
        _log("inspect_zapier_actions", {"selected_api": selected_api})
        if not selected_api:
            return json.dumps(APPS)
        actions = ACTIONS.get(selected_api, [])
        if tool_name:  # one action: with its parameters (like the real one)
            return json.dumps([{"app": selected_api, "selected_api": selected_api, "actions": [a for a in actions if a["tool_name"] == tool_name]}])
        # the app's list: no parameters (the real one gives them only per action)
        return json.dumps([{"app": selected_api, "selected_api": selected_api, "actions": [{k: v for k, v in a.items() if k != "params"} for a in actions]}])

    @s.tool()
    def execute_zapier_read_action(selected_api: str, action: str, tool_name: str = "", params: dict | None = None) -> str:
        """Run a search action."""
        _log("execute_zapier_read_action", {"selected_api": selected_api, "action": action, "tool_name": tool_name, "params": params})
        if tool_name == "gmail_find_email":
            return json.dumps({"results": DATA["mail"]})
        if tool_name == "gmail_get_attachment_by_filename":
            return json.dumps({"results": [{"file": DATA.get("attachment_url", ""), "filename": (params or {}).get("attachment_filename")}]})
        if tool_name == "google_calendar_find_calendars":
            return json.dumps({"results": [{"id": "team@group.example", "summary": "Team"}, {"id": "me@example.com", "summary": "Me", "primary": True}]})
        if tool_name == "google_calendar_find_events":
            if not (params or {}).get("calendarid"):  # Zapier's Find Events needs one (like the real one)
                return json.dumps({"isError": True, "error": "Missing argument values for required properties: `calendarid`"})
            return json.dumps({"results": DATA["events"]})
        return json.dumps({"error": "unknown action"})

    @s.tool()
    def execute_zapier_write_action(selected_api: str, action: str, params: dict | None = None) -> str:
        """Run a write action (send, delete...)."""
        _log("execute_zapier_write_action", {"action": action})
        return "sent"

elif MODE == "plain":
    @s.tool()
    def search_emails(query: str) -> str:
        """Search the inbox."""
        _log("search_emails", {"query": query})
        return json.dumps({"messages": DATA["mail"]})

    @s.tool()
    def list_events(time_min: str, time_max: str) -> str:
        """Events between two times."""
        _log("list_events", {"time_min": time_min, "time_max": time_max})
        return json.dumps({"events": DATA["events"]})

    @s.tool()
    def get_attachment(message_id: str, filename: str) -> str:
        """One attachment, base64."""
        _log("get_attachment", {"message_id": message_id, "filename": filename})
        if "attachment_json" in DATA:  # a test's own answer (a link, say)
            return json.dumps(DATA["attachment_json"])
        return json.dumps({"filename": filename, "data": base64.b64encode(DATA.get("attachment", "PDF").encode()).decode()})

    @s.tool()
    def send_email(to: str, body: str) -> str:
        """Send an email."""
        _log("send_email", {"to": to})
        return "sent"

elif MODE == "composio":
    @s.tool()
    def GMAIL_FETCH_EMAILS(query: str = "", max_results: int = 10) -> str:  # noqa: N802
        """Fetch emails."""
        _log("GMAIL_FETCH_EMAILS", {"query": query, "max_results": max_results})
        return json.dumps({"data": {"messages": DATA["mail"]}, "successful": True})

    @s.tool()
    def GOOGLECALENDAR_EVENTS_LIST(timeMin: str = "", timeMax: str = "") -> str:  # noqa: N802,N803
        """List events."""
        _log("GOOGLECALENDAR_EVENTS_LIST", {"timeMin": timeMin, "timeMax": timeMax})
        return json.dumps({"data": {"items": DATA["events"]}, "successful": True})

    @s.tool()
    def GMAIL_GET_ATTACHMENT(message_id: str, file_name: str, attachment_id: str = "") -> str:  # noqa: N802
        """Get an attachment."""
        _log("GMAIL_GET_ATTACHMENT", {"message_id": message_id})
        return json.dumps({"data": {"file": base64.b64encode(DATA.get("attachment", "PDF").encode()).decode()}, "successful": True})

elif MODE == "gmailmcp":  # a line-style Gmail and Calendar server: its schema and its text replies
    from typing import Annotated

    from pydantic import Field

    @s.tool()
    def gmail_search(query: Annotated[str, Field(description="Gmail search query")], max_results: int = 10) -> str:
        """Search Gmail."""
        _log("gmail_search", {"query": query, "max_results": max_results})
        return json.dumps({"messages": DATA["mail"]})

    @s.tool()
    def calendar_list_events(date_from: Annotated[str, Field(description="YYYY-MM-DD")],
                             date_to: Annotated[str | None, Field(description="YYYY-MM-DD, default = date_from")] = None) -> str:
        """List calendar events between two dates (inclusive), one per line: id | start-end | title | attendees."""
        _log("calendar_list_events", {"date_from": date_from, "date_to": date_to})
        last = date_to or date_from
        events = [e for e in DATA["events"] if date_from <= e["start"][:10] <= last]
        if not events:
            return f"No events from {date_from} to {date_to}." if date_to and date_to != date_from else f"No events on {date_from}."
        out, cur = [], ""
        for e in events:  # the server's line(): times as HH:MM, a "## day" line per day when the range has several
            d = e["start"][:10]
            if d != cur and date_to and date_to != date_from:
                out.append(f"## {d}")
                cur = d
            when = f"all day {e['start']}" if e.get("allDay") else f"{e['start'][11:16]}-{e['end'][11:16]}"
            who = f" | {', '.join(e['attendees'])}" if e.get("attendees") else ""
            where = f" @ {e['location']}" if e.get("location") else ""
            out.append(f"{e['id']} | {when} | {e['summary']}{who}{where}")
        return "\n".join(out)

    @s.tool()
    def calendar_create_event(summary: str, start: str, end: str) -> str:
        """Create an event."""
        _log("calendar_create_event", {"summary": summary})
        return "created"

if __name__ == "__main__":
    s.run()
