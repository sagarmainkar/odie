# Dialogue videos (experimental)

Odie can film a script you wrote: several characters speaking real lines, each in their own voice, with their mouths
moving as they speak and the line shown as a caption. You (and any LLM you like) write the story and the dialogue in
a note or a text file; Odie stages it word for word. It never writes or changes the story.

Without a script, videos are made exactly as before.

## Asking for one

In chat: "Make a video of my script *The lighthouse* (the note in my vault). Mira is Bella, Tobi is Michael. Warm
lamplight, a stormy sea outside." Odie reads the note (or the script you pasted), checks every speaker has a voice
and the script fits one video, and starts the video.

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

- `## Scene: <where>` starts a scene. The words tell the writer where it happens. A scene has at most 12 lines.
- `SPEAKER: what they say` is one line. Upper or lower case doesn't matter, and the usual Markdown is fine:
  `- ANNA: …`, `**ANNA:** …`, `ANNA (whispering): …` (the direction isn't spoken). Every speaker but `NARRATOR`
  needs a voice. A line can't contain `|`.
- `[pause N]` (or `[pause Ns]`) at the end of a line is the quiet after it, up to 10 seconds; on a scene's last line
  it is a beat before the cut. `[pause]` alone, or nothing, is a short breath between lines.
- Anything else (a title, front matter, notes) is ignored. A line like `Note: check this` reads as a speaker called
  Note, and Odie will say Note has no voice.
- A whole script is at most 6 minutes of speech and pauses.

## What you get

- The video in the chat, timed from the spoken lines.
- `timeline.json` next to it, in Odie's workspace (the chat says where): every line's speaker, voice, text, start
  and length, and every scene's start and length, in seconds, so the work can be re-voiced or re-cut elsewhere.

## A cast folder and a look (the same cast in every video)

For a work of several videos, keep a folder of character sheets in your vault (say `Stories/The lighthouse/cast`;
a cast folder must be in the vault or Odie's workspace) and, if you like, a style file. Then: "Make a video of scene 3 of *The lighthouse*, cast folder Stories/The
lighthouse/cast, look Stories/The lighthouse/look." Odie takes each character's voice from their sheet, gives the
writer each description word for word, and follows the look in every scene.

A sheet is a Markdown file with front matter; only `id` is required:

```
---
id: mira
display_name: Mira
canonical: "A tall woman in her thirties with short silver hair, a long green oilskin coat …"
voice: af_bella
ages:
  - act: Chapter one
    age: 34
    ref: refs/mira-34.jpg
refs: [refs/mira-front.jpg]
---
Notes for the writer (optional): who they are, how they move.
```

- `canonical` is used word for word: the writer must never vary how the character looks.
- `voice` is a voice of the engine chosen in Settings; `voices` in the request can still change it for one video.
- `ages`: mark acts in the script with `## Act: Chapter one` (or `## Act 2`); the writer draws each speaker at that
  act's age.
- `refs` (and an age's `ref`) are your own pictures inside the folder (JPEG, PNG or WebP). The writer can't see
  pictures; they reach the video as named pictures it may show (a portrait, a photo on a wall): up to three per
  character, six in a video, for those who speak in it.
- Only the sheets of characters who speak in the script go to the writer; a description is used up to 1,500
  characters.
- `asset: models/mira.vrm`: a 3D model of the character (see 3D characters).
- Files without front matter (a README, notes) are skipped.

After each video, a still of each speaker is saved as `refs/stills/<id>-<video>.jpg` in the cast folder (never over
a file that's there). To have later videos match it, add it to that character's `refs`.

The look file is plain text: palette, light, lens, grain, period. A complete invented example (two sheets, a look and
a script) is in `docs/examples/lighthouse/`.

## 3D characters

A character can appear as a 3D model instead of a drawing.

- Make one in VRoid Studio (free, by pixiv) and export it as `.vrm`, or download one from VRoid Hub. Each model there
  has its own terms: check that it allows use in videos.
- Put the file in the cast folder (for example `models/`) and add `asset: models/mira.vrm` to Mira's sheet. It can be
  `.vrm` or `.glb`, at most 40 MB (VRoid's export can shrink its textures).
- A plain `.glb` works too if it has face shapes (blend shapes) for the mouth. It doesn't get the VRM extras
  (expressions, swaying hair, arms posed down).
- A character without a model is drawn as before, so a scene can mix both: Mira in 3D, Tobi drawn in code.
- The mouth follows the loudness of the character's voice and guesses vowels from the words: it reads as talking in
  sync, not as exact lip shapes. The character also blinks, breathes and sways.
- The look is the model's own: an anime model stays anime.

The demo cast has no model.

## What it is not (yet)

- Characters are drawn in code: simple, consistent shapes, not realistic faces, unless their sheet gives a 3D model.
- No timed segment or brand kit in a dialogue video.
