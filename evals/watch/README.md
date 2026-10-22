# Watch eval

Made-up mails (`cases/`: 26 single mails; `inboxes/`: 3 inboxes of 10–15 mails with the hard ones among promotions)
through the real watch turn on a throwaway home, scored on what matters most: is each mail flagged for the user when it
asks something of them (and only then), and is a mail opened before deciding when its preview hides the ask.

    scripts/watch_eval.sh <provider>/<model> [case ids…]

It calls a model, so it isn't run in CI: run it before a release that changes the watch, and put the totals in the PR.

| Run (22 Oct 2026, ollama/deepseek-v4.1-flash:1017-cloud) | Judged right | Opened when the preview hid the ask |
|---|---|---|
| Old instructions, new reads (`read_mail` opens the mail; thread, search, sent-mail reads) | 60 of 61 | 5 of 5 |
| New instructions, run 1 | 61 of 61 | 5 of 5 |
| New instructions, run 2 | 61 of 61 | 5 of 5 |

Before the new reads, `read_mail` on a Gmail-style connector returned the listing's preview again, so a mail whose
preview reads like a newsletter could never be understood. A first baseline also showed that a refused tool (a Mac
reminder needing a tap) could end the turn without a report; the eval now has a recording calendar like the live watch,
and the instructions say to skip a refused tool and always report.
