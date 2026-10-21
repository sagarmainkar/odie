## This video is vertical (9:16, a reel)

The stage is **1080 × 1920**, taller than wide: `s.W` is 1080 and `s.H` is 1920, the centre (540, 960). Wherever
this guide gives positions or sizes for the 1920 × 1080 stage, work them out again for the tall one; never copy their
x and y as they are. The map, pictures and wipes take the stage's size by themselves.

A reel's own buttons and caption cover its top and bottom. Keep every word, label and character inside the safe
area: `s.safe` gives it in pixels (`top` 140, `bottom` 340, `side` 72), and the page's CSS has the same as
`--safe-top`, `--safe-bottom` and `--safe-side`. Nothing that matters below `s.H - s.safe.bottom` (y 1580), above
`s.safe.top` (y 140), or nearer an edge than `s.safe.side`.

- **One idea per screen, centred;** never two columns, never side by side.
- **Type at 64 px or larger;** at heading size, no line longer than 20 characters: break a longer title over lines.
- **Wide diagrams are re-laid out stacked,** one part above the next, never scaled down to fit the width.
- **A mascot or recurring character (a countdown character, when the brief has one) sits lower right, but above
  `--safe-bottom`:** its lowest point at y `s.H - s.safe.bottom` or higher.
- **The question card and the payoff card are full-bleed:** their background fills the whole stage, edge to edge;
  their words stay inside the safe area.
- **Draw with the kit.** Use a web picture or clip only when the topic needs a real one (a place, a person, a real
  thing): a reel's credits go in the post's caption, not on screen.
