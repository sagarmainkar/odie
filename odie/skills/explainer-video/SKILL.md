---
name: explainer-video
description: Make a narrated, animated explainer video (3Blue1Brown style) that plays in the chat, with real pictures, stock clips and a map when the topic needs them. Use for 'explain X with a video', 'make a video about…', 'animate how … works', 'a video of my trip'.
metadata:
  title: Explainer videos
  summary: "A narrated, animated explainer of any topic, 3Blue1Brown style, with real pictures, clips and a map when it needs them; it plays in the chat."
  adk_additional_tools: [make_video]
---
# Explainer videos

You brief the video; a separate writer makes it. `make_video` returns at once; in the background the writer turns
your brief into the narration and the animation, and the video is rendered and posted to this chat. You never write
narration or a page yourself.

## When to use it

When the user asks for a video, or for something explained or animated as one. Don't ask questions unless the topic
is unclear. Search first only if the topic needs current facts, and put what you found in the brief.

## Write the brief

The writer can't see this chat, the user's notes, memory or the web: it knows only the topic, the length, the brief
and the sources. So the brief carries everything else the video needs, research included:

- **who it's for and their level** ("a curious beginner");
- **the key points, in order,** one idea per point (they become the scenes);
- **examples and analogies** to show;
- **numbers, names and formulas** that must appear exactly;
- **facts from this chat or the notes** to use.

Only what the video needs, nothing private it doesn't use: plain text, up to 20,000 characters.

## What the user gave: sources

When the video is about something the user gave (pasted text, a note, a file), pass it in `sources`
instead of retyping it: the writer gets it word for word. Then keep the brief to the plan: who it's for, the story
in order, the look, what must appear. A source is `"my message"` (the user's latest message), a note's name or
path, or a text file's path in Odie's workspace; up to 5. If it came in an earlier message, put what the video needs
in the brief, or ask the user to paste it again.

## Pictures, clips and places

A film of something the viewer should see for real (people, places, things, a trip, a history, nature, a product)
needs material; an abstract topic ("how attention works") doesn't. Gather it before you call:

- **Web pictures:** `find_images(query)`, one query per theme or place: a history, one per ruler, battle or
  building; a trip plan, one or two per place. 6–20 pictures in all. Prefer the free ones (Unsplash, Pexels) and the
  user's own; take a web result only for a real thing a free photo can't show (a named painting, a monument), and
  never a watermarked preview.
- **The user's own trip:** `search_everything(only="photos", place=…, since=…, until=…)`; use each hit's
  `photo:<id>` address, not its /api/photos/ one.
- **Clips:** `find_clips(query)` for places and moods (waves, snow, a busy street; never faces): 0–6, of 5–15 s.
- **What the user gave here:** `upload:<id>`, `screenshot:<id>`.
- **3D and real surfaces:** any video can be 3D (a moving camera, lit objects); ask for it when depth helps (space,
  molecules, buildings). For a planet or a moon, `find_images("<name> texture map")` and pass the flat map, saying
  it is one: the writer wraps it on a sphere.

Pass them as `images` and `clips`, one line each: the address exactly as the tool gave it, " — ", then what it shows,
its mood and its orientation if unusual, then a web one's credit in brackets as the tool gave it:
`"https://… — the Red Fort at dusk, warm and still (Photo by A on Unsplash)"`,
`"photo:3F2A… — us at Nathula, prayer flags in the snow, 12 May 2026, portrait"`. The writer sees only these words.

A trip's brief gives the places in order, with dates. The map knows towns and cities, not every village, airport or
pass: give those as `lat, lon` (roughly is fine). Pune, Bagdogra, Gangtok, Lachung: Gangtok is known; write
"Bagdogra airport (26.681, 88.328)" and "Lachung (27.69, 88.74)".

In a private chat only the user's own pictures go in (web pictures and clips are left out), so don't search the web
for them. If a picture can't be fetched, the writer does without it: say nothing. If the result says something was
left out, tell the user in a few words (a library picture with a small copy: open it in Photos once).

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
- `sources`: only for what the user gave, e.g. `sources=["my message"]`.
- `sounds`: sound effects are on by default; pass `sounds=false` when the user says no sound effects.
- `voice_name`: leave it out unless the user asks for a voice; only a voice of the engine chosen in Settings (an
  error lists them).

## The reply

On `{"result": …}`, reply in one or two lines, with no emojis: it's being made, about how long (the range the result
gives), it will appear in this chat with a ping on the phone, and they can keep chatting meanwhile. Never repeat the
brief.

On `{"error": …}`: fix exactly that and call again. If it says there's no browser, tell the user what it says.
