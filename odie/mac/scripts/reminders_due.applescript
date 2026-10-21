-- argv: before (ISO local). JSON: [{id, title, due, list}] for open reminders due before then (or with no due date, left out).
on run argv
  set untilDate to my fromISO(item 1 of argv)
  set rows to {}
  tell application "Reminders"
    repeat with l in every list
      set lname to name of l
      repeat with r in (every reminder of l whose completed is false and due date ≤ untilDate)
        set end of rows to "{\"id\": " & my q(id of r) & ", \"title\": " & my q(name of r) & ", \"due\": " & my q(my iso(due date of r)) & ", \"list\": " & my q(lname) & "}"
      end repeat
    end repeat
  end tell
  return "[" & my joinList(rows, ", ") & "]"
end run
