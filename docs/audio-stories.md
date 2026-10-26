# Audio stories

Odie can make a dramatised story you listen to: a narrator, a voice for each character, the sound of the place
(surf, rain, a crowd, owls in the dark), effects where things happen, and music under it. It arrives in the chat as
**one finished file** in a story player, with a ping on your phone, like a podcast. Nothing is posted along the way.

## Asking for one

"Make me a 10-minute horror audio story", "a bedtime story to listen to", "a radio play about a lighthouse".

Odie runs a short, guided start with forms, and skips any step your message already answers:

1. **The genre:** horror, mystery, thriller, adventure, fantasy, sci-fi, romance, comedy, a true story, myths and
   folk tales, or a bedtime story; or your own idea.
2. **The story, the accent and the length**, in one form:
   - three short pitches for that genre, or your own idea;
   - the accent (British or American on Phonon; Indian too on Kokoro and OpenAI), asked here because the voices on
     offer depend on it;
   - the length: 3, 5, 8, 10 or 15 minutes.
3. **The cast**, in one form:
   - who tells it: a character, in the first person, or an outside storyteller;
   - a voice for each character, suggested and yours to change, each with a ▶ to hear it (on Phonon, the character
     voices too: a pirate captain, a witch, an old keeper);
   - how loud the sound sits under the voices: 10 to 40 %, at 25 %.

Then it's made in the background. A writer writes the script and chooses the sounds like an art director; Odie's
code speaks every line, mixes the sound and masters the file, the same way every time.

Voices come from the engine chosen in Settings → Voice. OpenAI's voices have no fixed accent, so the ▶ plays them
plain and the story adds the accent you chose.

## Where the sounds come from

From your Mac, never from Odie:

- **iMovie's sound library,** if iMovie is installed (it's free in the App Store): about 400 effects and ambiences, 200
  music beds and the theme music, read where iMovie keeps them.
- **Your own sounds:** put audio files in the `sounds` folder in Odie's home (`~/.odie/sounds/`); each subfolder is a
  category ("Rain", "My band"). They come first in what the writer sees.
- **Without iMovie,** Odie falls back to its own small kit of synthesized sounds (rain, wind, sea, a crowd, a bell…),
  with no music. Odie says once: "For richer sound, install iMovie (free in the App Store); Odie uses its sound
  library."

**Licence.** Odie uses these sounds where they are, on your own Mac. It never copies them into its repo and never
uploads them anywhere. The finished story is your file; sharing it is your choice (the player keeps its Share
button).

## The levels

The mix is code, not the model's choice:

- Every ambience and music file is first matched to the loudness of the voices, so a loud jingle and a quiet room
  tone land in the same place.
- The sound level then sets the ambience under the voices: **25 % is about 12 dB under the speech**, roughly a
  quarter of its loudness; 10 % is 20 dB under, 40 % is 8 dB under. Music sits 4 dB under the ambience.
- Between lines and in the opening, the ambience rises by up to 6 dB, never closer than 4 dB to the speech, and
  dips back smoothly under the next line.
- Ambience and music loop without a gap: each file's own fade-in and fade-out are cut, and every repeat crossfades
  into the next.
- Effects play once, set against the loudest word: "low" about 10 dB under it, "normal" 4 dB under, "up front"
  about level with it. They never land on a line's first word.
- The story is mastered to about −16 LUFS, like podcasts, by one gain (so the gap stays as mixed) and a limiter
  that keeps its true peak under −1.5 dBTP, as AAC in .m4a. The job's folder (`workspace/stories/<title>/`) keeps
  the script as written (`script.json`), every line and sound in time with its gain (`timeline.json`), and the gap,
  the loudness and the true peak measured on the finished file (`levels.json`).
