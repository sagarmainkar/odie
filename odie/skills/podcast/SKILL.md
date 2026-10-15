---
name: podcast
description: Make a podcast the user can play in the chat, NotebookLM style, two hosts talking a topic or this conversation through. Use for "make a podcast about…", "a podcast of our session", "turn this into an audio overview".
metadata:
  title: Podcasts
  summary: "Two hosts talk a topic or your conversation through; it plays in the chat."
---
# Podcast

Write a script for two hosts, then call `speak` with `style="podcast"`. The player appears under your reply.

## What it's about

- **"Our session", "this chat", "what we discussed":** this conversation. Use the decisions, the questions and the
  surprises, not a list of every message.
- **A topic:** what you know. If the user wants current facts, or facts from their notes, search the web or the notes
  first, then write.

## The hosts

- Two hosts, **Host A (a woman) and Host B (a man)**: Host A speaks first; the voices follow that order.
- **No names.** The hosts never say their own names or each other's, and never introduce themselves. The title
  doesn't name them either.

## How it sounds (NotebookLM style)

- **The opening:** go straight to what today's episode is about, in a line or two (no "welcome back, I'm…").
- **The middle:**
  - One host explains while the other asks, reacts ("wait, so…", "that's the part I didn't get"), and brings an
    example or an analogy.
  - They take turns: short turns, mostly one to three sentences.
  - Real points, specific details, a little humour. No filler.
- **The close:** a short wrap-up of the takeaways, then a warm sign-off.
- **Plain speech only:** no markdown, no bullet lists, no headings, no links, no emojis. Say numbers the way people
  say them.

## Length

- About 140 words a minute.
- **The default is 4 minutes** (about 560 words, 16–24 turns). If the user asks for a length, follow it, up to
  10 minutes (60 turns at most).

## The call

```
speak(style="podcast", title="<a short title about the topic>", script="""
Host A: Today we're digging into …
Host B: And the part that surprised me is …
…
""")
```

- One turn per line, `Host A: what they say` or `Host B: what they say`, all the way through.
- Keep each turn on one line. Never put both hosts on one line: "Host A: … Host B: …" is all read by Host A.
- No stage directions such as "(laughs)" or "[pause]". Say it in words instead ("Ha, fair point.").
- After it works, reply in one short line (what it's about and how long it is). Don't paste the script into the chat.
