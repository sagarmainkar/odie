---
name: explainer-video
description: Make a narrated, animated explainer video (3Blue1Brown style) that plays in the chat. Use for 'explain X with a video', 'make a video about…', 'animate how … works'.
metadata:
  title: Explainer videos
  summary: "A narrated, animated explainer of any topic, 3Blue1Brown style; it plays in the chat."
  adk_additional_tools: [make_video]
---
# Explainer videos

You brief the video; a separate writer makes it. `make_video` returns at once; in the background the writer turns
your brief into the narration and the animation, and the video is rendered and posted to this chat with a ping on
the phone. You never write narration or a page yourself.

## When to use it

When the user asks for a video, or for something explained or animated as one. Don't ask questions unless the topic
is unclear. Search first only if the topic needs current facts, and put what you found in the brief.

## Write the brief

The writer can't see this chat, the user's notes, memory or the web: it knows only the topic, the length and the
brief. So the brief carries everything the video needs:

- **who it's for and their level** ("a curious beginner", "an engineer who knows matrices");
- **the key points, in order,** one idea per point (they become the scenes);
- **examples and analogies** to show;
- **numbers, names and formulas** that must appear exactly;
- **facts from this chat or the user's notes** the video should use.

Put in only what the video needs, nothing private it doesn't use. Plain text, up to 6,000 characters; a short
numbered list is usually plenty.

## The call

```
make_video(
  topic="How attention works",
  minutes=2,
  brief="For a beginner who knows what a vector is. 1. Each word becomes a vector. 2. Each word scores how relevant
every other word is. 3. Softmax turns the scores into weights that add up to 1. 4. The new vector is the weighted
mix. Show softmax(QK^T / sqrt(d)) V. Example sentence: 'The cat sat on the mat'.",
)
```

- `topic`: a few words.
- `minutes`: the user's length, else 2; from 1 to 6.
- `voice_name`: leave it out unless the user asks for a voice; only a voice of the engine chosen in Settings (an
  error lists them).

## The reply

On `{"result": …}`, reply in one or two lines, with no emojis: it's being made, about how long (the range the result
gives), it will appear in this chat with a ping on the phone, and they can keep chatting meanwhile. Never repeat the
brief.

On `{"error": …}`: fix exactly that and call again. If it says there's no browser, tell the user what it says.
