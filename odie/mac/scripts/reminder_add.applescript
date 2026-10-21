-- argv: title, due (ISO local), list name ("" = the default list). JSON: {id, list}
on run argv
  set t to item 1 of argv
  set d to my fromISO(item 2 of argv)
  set wanted to item 3 of argv
  tell application "Reminders"
    if wanted is "" then
      set target to default list
    else
      set target to first list whose name is wanted
    end if
    tell target
      set r to make new reminder with properties {name:t, due date:d}
    end tell
    return "{\"id\": " & my q(id of r) & ", \"list\": " & my q(name of target) & "}"
  end tell
end run
