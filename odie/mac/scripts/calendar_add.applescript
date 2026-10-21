-- argv: title, start (ISO local), end (ISO local), calendar name ("" = the first writable one that isn't a system
-- calendar: Birthdays, holidays, Siri's, the Reminders app's), where, notes.
-- JSON: {id, calendar}; an unknown calendar errors with the names there are.
on run argv
  set t to item 1 of argv
  set d1 to my fromISO(item 2 of argv)
  set d2 to my fromISO(item 3 of argv)
  set wanted to item 4 of argv
  set loc to item 5 of argv
  set noteText to item 6 of argv
  tell application "Calendar"
    set target to missing value
    set names to {}
    repeat with c in every calendar
      set cname to name of c
      if not my system(cname) then set end of names to cname
      if wanted is not "" and cname is wanted then set target to c
      if wanted is "" and target is missing value and not my system(cname) then
        try
          if writable of c then set target to c
        end try
      end if
    end repeat
    if target is missing value then error "no calendar called " & wanted & "; there are: " & my joinList(names, ", ")
    tell target
      set e to make new event with properties {summary:t, start date:d1, end date:d2}
      if loc is not "" then set location of e to loc
      if noteText is not "" then set description of e to noteText
    end tell
    return "{\"id\": " & my q(uid of e) & ", \"calendar\": " & my q(name of target) & "}"
  end tell
end run

on system(cname)
  return (cname is "Siri Suggestions") or (cname is "Scheduled Reminders") or (cname is "Birthdays") or (cname contains "Holidays")
end system
