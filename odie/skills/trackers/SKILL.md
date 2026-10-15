---
name: trackers
description: Keep an eye on something in the background and tell the user when it matters (a match score, an order, a price, a delivery, the weather, a booking opening). Start, list or stop trackers.
metadata:
  title: Trackers
  summary: "Watches something in the background (a score, an order, a price) and tells you when it matters."
  adk_additional_tools: [track, list_trackers, stop_tracker]
---
# Trackers

Use when the user asks to track, watch, monitor or "tell me when" something, or says yes to Odie's offer to keep an
eye on it.

Trackers check as often as every 5 minutes (a page of the user's own account at most hourly). The 30 minutes you may
know is the mail and calendar watch, not trackers.

1. Work out what to check in plain words, so a background check can look it up alone. For example: "Arsenal vs
   Tottenham live score and match status", or "Amazon order 402-123 delivery status".
   When the user names a site, or wants live prices (option premiums, quotes), write the check as opening that page
   in the browser, step by step: "Open https://www.nseindia.com/option-chain?symbol=NIFTY, choose 29-Dec-2026 in the
   expiry date list, read the last price of the 23000 PE". Web searches don't see live prices.
2. Pick how often to check:
   - live matches: 5m
   - orders and deliveries: 2h
   - live prices while a market is open: 5m; other prices: 1h, or set times like "weekdays 10:00,15:30"
   - weekly things: "mon 09:00"
3. Pick when to tell them:
   - "change" (the default): when the result changes
   - "condition": when something holds, e.g. "below 3000" or "tickets on sale"
   - "always": every check, only if they ask for a regular update
4. Pick when to stop: until a date, or let the check end it (match over, order delivered). The default is 14 days.
5. If this chat read a page of the user's own account that shows the answer (their orders, a refund, a booking), pass
   its address as `page`. The user then decides on a card whether the tracker may check that page signed in; until they
   allow it, the check runs without signing in.
6. Call `track`, then confirm in one line: what you're checking, how often, and when it stops. Mention that they get
   a push notification and see it on Today.

To see trackers, call `list_trackers`. To stop one, call `stop_tracker` with its number. Ask first if it's unclear
which one they mean.
