---
name: podcast
description: Make a podcast the user can play in the chat, NotebookLM style, two hosts talking a topic or this conversation through. Use for "make a podcast about…", "a podcast of our session", "turn this into an audio overview".
metadata:
  title: Podcasts
  summary: "Two hosts talk a topic or your conversation through; it plays in the chat."
  adk_additional_tools: [make_podcast]
---
# Podcasts

You brief the podcast; a separate writer writes it. `make_podcast` returns at once; in the background the writer
turns your brief into a script for two hosts, it is spoken in two voices, and the player is posted to this chat with
a ping on the phone. You never write the script yourself.

## When to use it

When the user asks for a podcast or an audio overview. Don't ask questions unless the topic is unclear. If the user
wants current facts, or facts from their notes, search the web or the notes first and put what you found in the
brief.

## Write the brief

The writer can't see this chat, the user's notes, memory or the web: it knows only the topic, the length and the
brief. So the brief carries everything else:

- **the angle:** who it's for and what the episode is about;
- **the key points, in order;**
- **the facts it must use:** names, numbers and details from this chat or the notes.

**"Our session", "this chat", "what we discussed":** the writer never sees this conversation, so the brief is the
session: its decisions, the questions and the surprises, in order, with the facts that matter. Not a list of every
message.

Only what the podcast needs, nothing private it doesn't use: plain text, up to 6,000 characters.

## The call

```
make_podcast(
  topic="How vaccines train the immune system",
  minutes=4,
  brief="For a curious adult, no biology background. 1. What the immune system remembers. 2. How a vaccine shows it
a harmless copy. 3. Why boosters help. Use the example of the measles vaccine, about 97% effective after two doses.",
)
```

- `topic`: a few words.
- `minutes`: the user's length, else 4; from 1 to 10.

## The reply

On `{"result": …}`, reply in one or two lines, with no emojis: it's being made, about how long (the range the result
gives), it will appear in this chat with a ping on the phone, and they can keep chatting meanwhile. Never repeat the
brief.

On `{"error": …}`: fix exactly that and call again. In a private chat (one that read a signed-in site) with a
cloud voice it is refused, because the script would leave this computer: tell the user what the error says.
