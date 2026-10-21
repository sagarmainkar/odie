-- Shared handlers, inlined into each script by odie/mac/scripts.py at load time (AppleScript has no include).
-- JSON: q(s) quotes a string; iso(d) formats a date as 2026-10-21T15:04:00+05:30; fromISO(s) reads one.

on rep(t, a, b)
  set {tid, AppleScript's text item delimiters} to {AppleScript's text item delimiters, a}
  set parts to text items of t
  set AppleScript's text item delimiters to b
  set t to parts as text
  set AppleScript's text item delimiters to tid
  return t
end rep

on q(s)
  set s to s as text
  set s to my rep(s, "\\", "\\\\")
  set s to my rep(s, "\"", "\\\"")
  set s to my rep(s, (character id 13), "\\n")
  set s to my rep(s, (character id 10), "\\n")
  set s to my rep(s, (character id 9), "\\t")
  return "\"" & s & "\""
end q

on pad2(n)
  set s to (n as integer) as text
  if (count of s) is 1 then set s to "0" & s
  return s
end pad2

on offsetText()
  set secs to (time to GMT)
  set sgn to "+"
  if secs < 0 then
    set sgn to "-"
    set secs to -secs
  end if
  return sgn & my pad2(secs div 3600) & ":" & my pad2((secs mod 3600) div 60)
end offsetText

on iso(d)
  return (year of d as text) & "-" & my pad2((month of d) as integer) & "-" & my pad2(day of d) & "T" & my pad2(hours of d) & ":" & my pad2(minutes of d) & ":" & my pad2(seconds of d) & my offsetText()
end iso

on isoDay(d)
  return (year of d as text) & "-" & my pad2((month of d) as integer) & "-" & my pad2(day of d)
end isoDay

-- "2026-10-21T15:04" or "2026-10-21T15:04:00" or "2026-10-21", local time
on fromISO(s)
  set d to current date
  set y to (text 1 thru 4 of s) as integer
  set mo to (text 6 thru 7 of s) as integer
  set dd to (text 9 thru 10 of s) as integer
  set hh to 0
  set mi to 0
  set ss to 0
  if (count of s) ≥ 16 then
    set hh to (text 12 thru 13 of s) as integer
    set mi to (text 15 thru 16 of s) as integer
  end if
  if (count of s) ≥ 19 then set ss to (text 18 thru 19 of s) as integer
  set day of d to 1
  set year of d to y
  set month of d to mo
  set day of d to dd
  set time of d to hh * 3600 + mi * 60 + ss
  return d
end fromISO

on joinList(parts, sep)
  set {tid, AppleScript's text item delimiters} to {AppleScript's text item delimiters, sep}
  set t to parts as text
  set AppleScript's text item delimiters to tid
  return t
end joinList

on firstChars(t, n)
  set t to t as text
  if (count of characters of t) > n then return (text 1 thru n of t)
  return t
end firstChars
