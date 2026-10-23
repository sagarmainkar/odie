# Dialogue videos (experimental)

Odie can film a script you wrote: several characters speaking real lines, each in their own voice, with their mouths
moving as they speak and the line shown as a caption. You (and any LLM you like) write the story and the dialogue in
a note or a text file; Odie stages it word for word. It never writes or changes the story.

Without a script, videos are made exactly as before.

## Asking for one

In chat: "Make a video of my script *The lighthouse* (the note in my vault). Mira is Bella, Tobi is Michael. Warm
lamplight, a stormy sea outside." Odie reads the note, checks every speaker has a voice, and starts the video.

Voices are the voices of the engine chosen in Settings → Voice. The narrator needs none: the video voice speaks for
them.

## The script format

```
## Scene: The lamp room, a stormy night
NARRATOR: The storm had kept the lamp burning since noon.
MIRA: You should sleep. I'll watch the light. [pause 1.2]
TOBI: Not yet. Something's out there.

## Scene: The gallery, dawn
MIRA: There. A sail.
TOBI: They made it.
```

- `## Scene: <where>` starts a scene. The words tell the writer where it happens.
- `SPEAKER: what they say` is one line. Upper or lower case doesn't matter. Every speaker but `NARRATOR` needs a
  voice.
- `[pause N]` at the end of a line is the quiet after it, in seconds. Without it, a short breath.
- Anything else (a title, front matter, notes) is ignored. A line like `Note: check this` reads as a speaker called
  Note, and Odie will say Note has no voice.

## What you get

- The video in the chat, timed from the spoken lines.
- `timeline.json` next to it (the chat says where): every line's speaker, voice, text, start and length, and every
  scene's start and length, in seconds, so the work can be re-voiced or re-cut elsewhere.

## What it is not (yet)

- Characters are drawn in code: simple, consistent shapes, not realistic faces or 3D models.
- No timed segment or brand kit in a dialogue video.
- Cast folders (character sheets used across videos), a style file and reference images are the next step.
