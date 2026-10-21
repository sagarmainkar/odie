## This video has a timed segment of __SECONDS__ seconds

- **Mark the segment in `Video.scenes`:** `timed_start: true` on its first scene and `timed_end: true` on its last,
  next to `draw` (`{timed_start: true, draw(t, s) { ... }}`); both on one scene when the segment is one scene.
  Everything between the flags is the __SECONDS__-second segment; scenes before and after are untimed (an opening
  question, a pause, a closing card) and keep their natural length.
- **The segment's narration: about __WORDS__ words** (__FEWEST__ to __MOST__), for __SECONDS__ seconds of speech. Odie
  fits the segment's recorded voice to exactly __SECONDS__ seconds, its first word to its last; the whole video still
  keeps the length asked for.
- **The segment clock: `s.left()`.** It gives the seconds left on the segment, read from the measured voice:
  __SECONDS__ at the segment's first word, down to 0 at its last word, and `null` before the first word. Never count
  from __SECONDS__ yourself, never from `s.length` or the video's length: only `s.left()`.
- **A countdown character (when the brief has one)** is drawn only when `s.left()` is not `null`: it shows
  `Math.ceil(s.left())` (__SECONDS__ at the first word), counts down with the voice to 0 on the last word, then blinks
  once; Odie plays a chime at 0. The scenes after it are ordinary ones; no 3-2-1 and no countdown before it.
