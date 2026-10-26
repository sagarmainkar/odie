---
name: audio-story
description: Make an audio story the user listens to in the chat, a dramatised, immersive story with a narrator, character voices, ambient sound, effects and music, delivered as one finished file. Use for "make me an audio story", "a radio play", "an audio drama", "a story to listen to", "a bedtime story" to hear.
metadata:
  title: Audio stories
  summary: "A dramatised story with a narrator, voices, ambience and music, as one file that plays in the chat."
  adk_additional_tools: [story_voices, make_audio_story]
---
# Audio stories

You run a quick, guided start with forms; then `make_audio_story` does the rest in the background: a separate writer
writes the script and picks the sounds, and Odie's code speaks every line, mixes the sound and posts **one finished
file** to this chat with a ping on the phone.

Never use `speak` to build a story or to play samples of it, and never stitch audio together in the shell: the user
gets one finished file and nothing in between.

## The guided start

Each step is **one form**, prefilled with your best guess (the user can always just type instead). Skip a step the
user has already answered ("a 10-minute horror story about a lighthouse" skips steps 1 and 2).

1. **Genre:** a radio of about 11 options, each with a one-line note: horror, mystery, thriller, adventure, fantasy,
   sci-fi, romance, comedy, true story (history), mythology and folk tales, bedtime (kids). Add a text field "or your
   own idea".
2. **The story:** three short pitches for that genre, each a one-line logline as a radio option with a note, plus a
   text field "your own idea".
3. **Cast and shape**, in one form. Call `story_voices()` first: it gives the accents the chosen voice engine offers.
   Then `story_voices(accent)` gives the voices as ready-made form options; use them as they are.
   - **accent:** a radio of the accents it gave;
   - **narrator:** a radio, "a character tells it" or "an outside storyteller", then the narrator's voice;
   - **each character:** a voice select prefilled with your suggestion, from `voices`; for a role a character voice
     lifts (a pirate captain, a witch, an old keeper), from `characters` too (Phonon only);
   - **length:** a radio, 3 / 5 / 8 / 10 / 15 minutes;
   - **sound level:** a slider from 10 to 40 %, at 25 %.
   At most 12 fields: for a big cast, cast the main characters and let minor ones share a voice.
4. Then call `make_audio_story` once (below), and say in one or two lines that it's being made.

The accent comes first to keep it simple: British or American on Phonon, Indian too on Kokoro and OpenAI. On
OpenAI the ▶ plays a voice without the accent; the story adds it.

## Sound

Odie uses the sound library installed with iMovie on this Mac, and the user's own sounds in the `sounds` folder of
Odie's home. Without iMovie it falls back to Odie's own small kit, with no music, and `make_audio_story`'s result
says so: then tell the user once, "For richer sound, install iMovie (free in the App Store); Odie uses its sound
library." The writer chooses the sounds; you never pick files or volumes.

## The call

```
make_audio_story(
  title="The Lighthouse at Rook Point",
  genre="mystery",
  premise="An old keeper hears a ship's bell on a night no ship is out.",
  cast=[{"id": "narrator", "name": "Narrator", "voice": "Fairy Godmother", "about": "an outside storyteller"},
        {"id": "keeper", "name": "The keeper", "voice": "Old Mortlake", "about": "the last keeper, gruff and alone"}],
  narrator="narrator",
  accent="British",
  minutes=10,
  sound_level=25,
  brief="Slow and eerie; the ending stays open.",
)
```

- `cast`: the narrator and each character with the voice chosen in the form (a `value` from `story_voices`).
- `narrator`: `"narrator"` for an outside storyteller (in the cast as id `narrator`), or a character's id to tell it
  in the first person.
- `minutes` 2 to 15; `sound_level` 10 to 40 (the slider's value).

## The reply

On `{"result": …}`: one or two lines, no emojis: it's being made, about how long, it will appear in this chat with
a ping on the phone. On `{"error": …}`: fix exactly that and call again.
