-- argv: id ("mac:<n>"), attachment name, folder (POSIX path, exists). JSON: {path}
on run argv
  set raw to item 1 of argv
  set n to (text 5 thru -1 of raw) as integer
  set wanted to item 2 of argv
  set folder to item 3 of argv
  if folder does not end with "/" then set folder to folder & "/"
  tell application "Mail"
    set m to first message of inbox whose id is n
    repeat with a in mail attachments of m
      if (name of a) is wanted then
        set target to POSIX file (folder & wanted)
        save a in target
        return "{\"path\": " & my q(folder & wanted) & "}"
      end if
    end repeat
  end tell
  error "no attachment called " & wanted
end run
