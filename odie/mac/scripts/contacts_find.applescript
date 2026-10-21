-- argv: query, limit. JSON: [{name, emails: [], phones: [], birthday}] for people whose name holds the query.
on run argv
  set query to item 1 of argv
  set lim to (item 2 of argv) as integer
  set rows to {}
  tell application "Contacts"
    set found to (every person whose name contains query)
    set n to 0
    repeat with p in found
      set n to n + 1
      if n > lim then exit repeat
      set ems to {}
      repeat with em in emails of p
        set end of ems to my q(value of em)
      end repeat
      set phs to {}
      repeat with ph in phones of p
        set end of phs to my q(value of ph)
      end repeat
      set bd to ""
      try
        set bdate to birth date of p
        if bdate is not missing value then set bd to my isoDay(bdate)
      end try
      set end of rows to "{\"name\": " & my q(name of p) & ", \"emails\": [" & my joinList(ems, ", ") & "], \"phones\": [" & my joinList(phs, ", ") & "], \"birthday\": " & my q(bd) & "}"
    end repeat
  end tell
  return "[" & my joinList(rows, ", ") & "]"
end run
