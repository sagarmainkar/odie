## This is a one-minute video

- **Narration: about 140 words** (115 to 170), for one minute of speech. Odie fits the recorded voice to exactly
  60 seconds, so write for a minute, never more.
- **It opens silent on the question card.** For 2.5 s before the first word, scene 1 is shown as it is at `t = 0`:
  the question card, complete and still. Draw it whole at `t = 0`; the narration starts after it.
- **The narration clock: `s.left()`.** It gives the seconds left on the narration, read from the measured voice: 60
  at the first word, down to 0 at the last word, and `null` before the first word (the silent opening). Never count
  from 60 yourself, never from `s.length` or the video's length: only `s.left()`.
- **A countdown character (when the brief has one)** is drawn only when `s.left()` is not `null`: he enters
  at the first word showing `Math.ceil(s.left())` (60), counts down with the voice to 0 on the last word, then blinks
  once. Odie plays the chime and cuts there: nothing after 0, no outro card, no 3-2-1.
