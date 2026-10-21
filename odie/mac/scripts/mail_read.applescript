-- argv: id ("mac:<n>"), bodyChars. JSON: {id, from, subject, at, body, attachments: [{name, size}]}
on run argv
  set raw to item 1 of argv
  set n to (text 5 thru -1 of raw) as integer
  set bodyChars to (item 2 of argv) as integer
  tell application "Mail"
    set m to first message of inbox whose id is n
    set body to ""
    try
      set body to my firstChars(content of m, bodyChars)
    end try
    set atts to {}
    try
      repeat with a in mail attachments of m
        set sz to 0
        try
          set sz to file size of a
        end try
        set end of atts to "{\"name\": " & my q(name of a) & ", \"size\": " & sz & "}"
      end repeat
    end try
    return "{\"id\": " & my q(raw) & ", \"from\": " & my q(sender of m) & ", \"subject\": " & my q(subject of m) & ", \"at\": " & my q(my iso(date received of m)) & ", \"body\": " & my q(body) & ", \"attachments\": [" & my joinList(atts, ", ") & "]}"
  end tell
end run
