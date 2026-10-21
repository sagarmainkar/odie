-- argv: since (ISO local time), limit. Newest first; the inbox is listed newest first, so the walk stops at the
-- first message older than `since`. JSON: [{id, from, subject, at, snippet, attachments: [{name, size}]}]
on run argv
  set cutoff to my fromISO(item 1 of argv)
  set lim to (item 2 of argv) as integer
  set previewFor to 8
  set rows to {}
  tell application "Mail"
    set n to 0
    repeat with m in (every message of inbox)
      if (date received of m) ≥ cutoff then
        set n to n + 1
        if n > lim then exit repeat
        set snippet to ""
        if n ≤ previewFor then
          try
            set snippet to my firstChars(my squash(content of m), 300)
          end try
        end if
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
        set rfc to ""
        try
          set rfc to message id of m
        end try
        set end of rows to "{\"id\": " & my q("mac:" & (id of m as text)) & ", \"message_id\": " & my q(rfc) & ", \"from\": " & my q(sender of m) & ", \"subject\": " & my q(subject of m) & ", \"at\": " & my q(my iso(date received of m)) & ", \"snippet\": " & my q(snippet) & ", \"attachments\": [" & my joinList(atts, ", ") & "]}"
      else
        exit repeat
      end if
    end repeat
  end tell
  return "[" & my joinList(rows, ", ") & "]"
end run

on squash(t)
  set t to my rep(t, (character id 13), " ")
  set t to my rep(t, (character id 10), " ")
  set t to my rep(t, (character id 9), " ")
  repeat while t contains "  "
    set t to my rep(t, "  ", " ")
  end repeat
  return t
end squash
