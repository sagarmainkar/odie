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
| New instructions + review fixes (actions now scored: none taken for the injection mail) | 60 of 61 (one card statement also flagged as needing the user) | 5 of 5 |

Before the new reads, `read_mail` on a Gmail-style connector returned the listing's preview again, so a mail whose
preview reads like a newsletter could never be understood. A first baseline also showed that a refused tool (a Mac
reminder needing a tap) could end the turn without a report; the eval now has a recording calendar like the live watch,
and the instructions say to skip a refused tool and always report.

## Threads, piles and drafts (Plan B, 22 Oct 2026)

The watch now reviews the threads it follows (`open_threads`) before new mail, labels each needs-you item (pile, one
suggestion, one escape, a drafted reply when one is owed) and tracks orders, bills, replies owed and deadlines with
`track`. Two lifecycle cases: a reply the user already sent (the thread must close) and one two days overdue (it must
come back as needing the user).

| Run (ollama/deepseek-v4.1-flash:1017-cloud) | Judged right | Opened | Pile fits | Tracked | Older threads |
|---|---|---|---|---|---|
| Run 1 | 62 of 63 | 5 of 5 | 20 of 20 | 7 of 7 | 2 of 2 |
| Run 2 | 62 of 63 | 5 of 5 | 20 of 20 | 7 of 7 | 2 of 2 |

The one difference in both runs was a "new sign-in to your account" notice the watch flagged; its instructions ask for
exactly that (a login the user may not have made), so the case now expects it flagged, pile alerts.
