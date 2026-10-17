---
name: research
description: Research a question in the background and post a report with its sources to the chat. Use for anything time-consuming that is mostly reading - "research…", "look into…", "compare…", "find out…", "a report on…".
metadata:
  title: Research
  summary: "Looks a question up on the web and in your notes, then posts a report with its sources."
  adk_additional_tools: [make_research]
---
# Research

You brief the research; a separate writer does it. `make_research` returns at once; in the background the writer
searches the web and the user's notes, reads what matters and writes a report (a short answer, the findings, the
sources), and the report is posted to this chat as a Markdown file with a ping on the phone. You never do the
research yourself.

## When to use it

For anything time-consuming that is mostly reading: "research…", "look into…", "compare…", "find out…", "a report
on…", where answering well means several searches and pages. A quick fact is still one `web_search` in the chat. A
Word document or deck of what the chat already knows is the documents skill. Don't ask questions unless the question
itself is unclear.

## Write the brief

The writer can't see this chat or the user's memory: it knows only the topic and the brief. So the brief carries:

- **the question,** as the user means it;
- **what matters to them:** their budget, their place, who it's for, what they'll do with the answer;
- **what is known already:** facts and decisions from this chat, so the writer doesn't look them up again;
- **what to skip,** and **where to look:** their notes on it, sites they trust.

Only what the research needs, nothing private it doesn't use: plain text, up to 6,000 characters.

## What the user gave: sources

Pass what the user gave (pasted text, a note, a file) in `sources` instead of copying it into the brief: the
writer gets it word for word, and the brief stays the plan. A source is `"my message"` (their latest message), a
note's name or path, or a text file's path in Odie's workspace; up to 5.

## The call

```
make_research(
  topic="Which kettle to buy",
  brief="For a family of four in Pune, under ₹3,000. Steel or glass, which lasts longer? They boil water four or
five times a day. Skip travel kettles. Compare three or four models with prices.",
)
```

- `topic`: a few words.

## The reply

On `{"result": …}`, reply in one or two lines, with no emojis: it's being researched, about how long (the range the
result gives), the report will appear in this chat with a ping on the phone, and they can keep chatting meanwhile.
Never repeat the brief.

On `{"error": …}`: fix exactly that and call again. In a private chat (one that read a signed-in site) it is
refused, because the writer's searches would each need the user's tap: tell the user to ask outside the private
chat.
