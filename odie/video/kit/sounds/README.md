# Sound effects for explainer videos

The short sounds the video writer places under the narration by name: a whoosh on a cut, footsteps under an army,
rain under a monsoon shot. Their names, lengths and the words the writer reads are in `odie/video/sounds.py`; each
name is the file `<name>.wav` here.

- Mono, 44.1 kHz, 16-bit WAV, each peaking at about −3 dBFS.
- Hits play once at their own length (3 s at most). Loops are 4–8 s and seamless: played round and round there is
  no join.
- About 6.7 MB together; the limit is 8 MB (a test holds it).

## Where they come from

Every file is synthesized by `scripts/sounds/build_sounds.py` from sines and seeded noise: nothing is recorded or
taken from anywhere, so there is no licence to carry, and the same files come out on every run. Each sound is one
function in that script with a comment saying what it is made of. They are dedicated to the public domain
([CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)).

Rebuild them all from the repository root with `uv run python scripts/sounds/build_sounds.py`, or some of them with
their names: `uv run python scripts/sounds/build_sounds.py rain sea`.

## Replacing one with a recording

A recording can take a synthesized sound's place, file for file, under the same name:

1. It must be CC0 (public domain), so a video never owes anyone a credit: Freesound's "Creative Commons 0" filter
   finds them. Not CC BY, not "free for personal use".
2. Make it mono 44.1 kHz 16-bit: `ffmpeg -i recording.wav -ac 1 -ar 44100 -c:a pcm_s16le rain.wav`.
3. A hit stays at 3 s or under. A loop is 4–8 s, and its end must lead into its start: fade its last 0.3 s into
   its first, as the script does, and listen to it looping.
4. Bring its loudest peak to about −3 dBFS (`ffmpeg -i rain.wav -af volumedetect -f null -` gives `max_volume`;
   raise or lower it by the difference with `-af volume=<n>dB`).
5. Save it over `<name>.wav`; if its length changed, change that sound's `seconds` in `odie/video/sounds.py`;
   run `uv run pytest tests/test_video_sounds.py`.
6. Add a line under "Recordings" below: the name, where it came from (the page's address), its author and the date.
   After that, rebuild the others by name only: the script without names would write over the recording.

## Recordings

None yet: every file is synthesized.
