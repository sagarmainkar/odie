## This is a dialogue video: you stage a script

The message gives the script: its scenes in order, each with where it is, and its lines numbered across the video,
each with who speaks. **The script is fixed: never change, add or drop a word, and write no narration.** Odie speaks
every line in its speaker's own voice and times the video from them. You draw the page.

- **One scene per script scene, in order:** `Video.scenes([...])` has exactly as many scenes as the script. Scene
  lengths come from the spoken lines; `s.beats` are where each of the scene's lines starts, so `s.beatAt(t)` is the
  line being spoken in this scene (0 for its first line).
- **The cast is drawn in code** (2D shapes, or three.js): give each speaker one look and keep it in every scene
  (the same colours, shape, size and clothes; the brief may describe them). Make them people or creatures of simple,
  clear shapes, never a realistic human face.
- **Mouths follow the voice:** every character has a mouth with three shapes, drawn from `s.mouth("anna")`: 0 closed,
  1 half open, 2 open. It opens and closes with that speaker's own line and stays closed while others speak.
- **Who is speaking:** `s.speaking()` gives `{speaker, index, progress, text}` for the line playing in this frame
  (index across the video, progress 0..1 through it), or `null` between lines. Turn the speaker a little toward the
  one they talk to, light them a touch brighter, or move them slightly; the listener reacts (a nod, a glance).
- **Captions:** show the line being spoken at the bottom of the stage, from `s.speaking().text`, unless the brief
  says no captions: one line at a time, white on a soft dark band, never over a face.
- **Staging:** set each scene where the script says, with a background and props drawn in code, and frame the
  characters as a film would (a two-shot, a close-up for an important line, a slow push-in). The camera may move;
  the characters stay recognisable.
- **Submit:** `submit_video` takes the title and the page only (no narration).
