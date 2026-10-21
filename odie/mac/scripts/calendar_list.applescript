-- argv: none. JSON: [{name, writable}] for the calendars events may go into (system ones left out).
on run argv
  set rows to {}
  tell application "Calendar"
    repeat with c in every calendar
      set cname to name of c
      if not my system(cname) then
        set w to "false"
        try
          if writable of c then set w to "true"
        end try
        set end of rows to "{\"name\": " & my q(cname) & ", \"writable\": " & w & "}"
      end if
    end repeat
  end tell
  return "[" & my joinList(rows, ", ") & "]"
end run

on system(cname)
  return (cname is "Siri Suggestions") or (cname is "Scheduled Reminders") or (cname is "Birthdays") or (cname contains "Holidays")
end system
