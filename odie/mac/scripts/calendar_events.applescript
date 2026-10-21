-- argv: start (ISO local), end (ISO local). JSON: [{id, title, start, end, where, attendees: [email], calendar, all_day}]
on run argv
  set d1 to my fromISO(item 1 of argv)
  set d2 to my fromISO(item 2 of argv)
  set rows to {}
  tell application "Calendar"
    repeat with c in every calendar
      set cname to name of c
      if my skipped(cname) then
        -- Siri's guesses and the Reminders app's own items (those come through mac_reminders) are not events
      else
      repeat with e in (every event of c whose start date ≥ d1 and start date ≤ d2)
        set who to {}
        try
          repeat with a in attendees of e
            set em to ""
            try
              set em to email of a
            end try
            if em is "" then set em to display name of a
            set end of who to my q(em)
          end repeat
        end try
        set loc to ""
        try
          set loc to location of e
          if loc is missing value then set loc to ""
        end try
        set ad to "false"
        try
          if allday event of e then set ad to "true"
        end try
        set end of rows to "{\"id\": " & my q(uid of e) & ", \"title\": " & my q(summary of e) & ", \"start\": " & my q(my iso(start date of e)) & ", \"end\": " & my q(my iso(end date of e)) & ", \"where\": " & my q(loc) & ", \"attendees\": [" & my joinList(who, ", ") & "], \"calendar\": " & my q(cname) & ", \"all_day\": " & ad & "}"
      end repeat
      end if
    end repeat
  end tell
  return "[" & my joinList(rows, ", ") & "]"
end run

on skipped(cname)
  return (cname is "Siri Suggestions") or (cname is "Scheduled Reminders")
end skipped
