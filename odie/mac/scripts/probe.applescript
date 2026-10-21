-- argv: the app's name. One harmless Apple event, so macOS asks for the automation permission when it hasn't yet.
on run argv
  set appName to item 1 of argv
  if appName is "Mail" then
    tell application "Mail" to set n to count of accounts
  else if appName is "Calendar" then
    tell application "Calendar" to set n to count of calendars
  else if appName is "Reminders" then
    tell application "Reminders" to set n to count of lists
  else if appName is "Contacts" then
    tell application "Contacts" to set n to count of groups
  else
    error "unknown app " & appName
  end if
  return "ok"
end run
