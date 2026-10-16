---
name: explainer-video
description: Make a narrated, animated explainer video (3Blue1Brown style) that plays in the chat. Use for 'explain X with a video', 'make a video about…', 'animate how … works'.
metadata:
  title: Explainer videos
  summary: "A narrated, animated explainer of any topic, 3Blue1Brown style; it plays in the chat."
  adk_additional_tools: [save_video_page, make_video]
---
# Explainer videos

You write the narration and one page that draws every scene. `save_video_page` keeps the page, and `make_video` checks
everything in seconds, then narrates, renders a 1080p MP4 in the background and posts it to this chat.

## The flow

1. **Plan the scenes in a few lines:** one idea per scene, what is said and what is shown. Search first only if the
   topic needs current facts. Don't ask questions unless the topic is unclear. Keep the plan short and **never draft
   the page in your thinking**: a reply has limited room, and a page drafted there leaves none to send it.
2. **Save the page:** `save_video_page(page="<script>…</script>")`, one scene per narration string, in order. It
   returns a name, like `page-1`.
3. **Make the video:** `make_video(title="<the topic, short>", narration=[...], page_file="page-1")`, one string of
   narration per scene.
4. **`{"error": …}`:** fix exactly that and call again, in this same turn (see the last section). A page problem:
   save the fixed page (it gets a new name) and call `make_video` with that name.
5. **`{"result": …}`:** reply in one or two lines, with no emojis: it's being made, about how long (the range the
   result gives), it will appear in this chat with a ping on the phone as soon as it's ready, and they can keep
   chatting meanwhile. Never wait silently; never repeat the script or paste the page.

## Length

- About 140 words of narration make a minute: a scene of 50 words lasts about 21 seconds.
- **Default about 3 minutes:** about 420 words in 5–12 scenes (often 20–80 words a scene).
- The user's length wins, from 1 to 6 minutes. Over 6 minutes is refused; a scene has at most 4,000 characters, a
  video at most 40 scenes and the page at most 300 KB.

## Narration

- Plain speech for the ear: short sentences; no markdown, lists, symbols, links or emojis. Numbers and formulas as
  they are said: "two to the power of ten", "Q times K transpose, over the square root of d".
- One string per scene, in order. Scene k is on screen while its string is spoken, and the scene lasts exactly as
  long as its speech. Say what is on screen as it appears.
- The voice is the one chosen in Settings. Pass `voice_name` only when the user asks for a voice, and only a voice
  of that same engine (the error lists them).

## The page contract

The page is the body of an HTML page: one `<script>` that calls `Video.scenes([...])` once. The kit is already in the
page as globals: `THREE` (three.js r158, core only: no addons, loaders, OrbitControls or TextGeometry), `katex`
and `Video`. Nothing else loads: no `<script src>`, no links, no images, no web fonts (every request is refused).

```js
Video.scenes([
  {
    setup(s) { /* optional; runs once: build three.js objects, add them to s.three.scene, keep them on this */ },
    draw(t, s) { /* every frame: t is seconds into this scene, from 0 to s.length */ },
  },
  {draw(t, s) { /* scene 2 */ }},
]);
```

- Write `setup(s) {…}` and `draw(t, s) {…}` as methods, not arrow functions, so `this` is the scene: what setup
  keeps on `this` (`this.cube = …`) is there in draw.
- `s.length` is the scene's spoken length in seconds. Time reveals as parts of it, to match the words:
  `s.at(t, 0.5 * s.length, 0.6 * s.length)`. After the scene ends (a 0.5 s breath) its last picture holds.
- **A frame is a pure function of t.** Several tabs draw frames out of order, so:
  - draw sets every property it animates on every frame (position, scale, rotation, opacity, colour), not only
    after some moment;
  - objects are created in setup, never in draw (draw only changes them);
  - no `requestAnimationFrame`, `setTimeout`, `Date`, `performance.now` or `Math.random` (use `s.random(seed)`).
- Before every frame the kit puts back the camera (position, orientation, fov, zoom, near, far, aspect, view offset:
  home is (0, 0, 10), fov 45, looking at the origin), the renderer (clear colour, tone mapping and exposure, colour
  space, auto-clear, viewport, scissor), the 2D canvas (cleared, its state reset) and every text and formula
  (hidden). So a text shows only in frames whose draw calls `s.text` for it, and a camera move is set in draw:
  `s.three.camera.position.set(s.lerp(0, 4, s.at(t, 1, 8)), 1, 10); s.three.camera.lookAt(0, 0, 0);` (after
  changing `fov`, call `s.three.camera.updateProjectionMatrix()`).
- Each scene has its own three.js scene, `s.three.scene`, softly lit (a sky light and a key light from the upper
  right), so `MeshStandardMaterial` looks shaded. Objects never carry over to another scene. To fade a 3D object,
  set `material.transparent = true` in setup and `material.opacity` in draw.
- Positions. Text, formulas and `s.ctx`: pixels on the 1920 × 1080 stage, (0, 0) at the top left. A text's `y` is
  its vertical middle (y defaults to 540, the stage's middle); its `x` is its middle (align "center", the default; x
  defaults to 960), its left edge ("left") or its right edge ("right"). Text and formulas default to the colour
  `s.colors.text` (#ECECEC). Three.js: from the home camera, z = 0 shows x from -7.4 to 7.4 and y from
  -4.1 to 4.1 (y up): those are the picture's edges, so keep things within about x ±6 and y ±3.4.
- Layers, back to front: three.js, the 2D canvas `s.ctx`, then text and formulas.

The helpers on `s`:

| helper | what it does |
|---|---|
| `s.at(t, from, to)` | eased progress 0 to 1 across seconds [from, to]; 0 before, 1 after. `s.at(1.5, 1, 2)` is 0.5 |
| `s.fade(t, inAt, outAt)` | an opacity: fades in over 0.6 s from inAt; if outAt is given, gone again by outAt |
| `s.ease(x)` | smooth in-out of x in 0..1 |
| `s.lerp(a, b, p)` | the value p of the way from a to b: `s.lerp(-3, 3, s.at(t, 0, 2))` |
| `s.count(from, to, p)` | a whole number between from and to, for counters: `String(s.count(0, 1000, p))` |
| `s.random(seed)` | a seeded generator of numbers in 0..1: `const rnd = s.random(7); rnd()`. Use it in setup (to place things once) or make it afresh in draw each frame; never call one made in setup from draw |
| `s.text(id, words, o)` | words for this frame. `o`: `x` (960), `y` (540), `size` (48), `color` (`s.colors.text`), `align` ("center"), `weight` (400), `opacity` (1), `write` (0..1 reveals it left to right). `"\n"` breaks a line |
| `s.tex(id, latex, o)` | a KaTeX formula for this frame; `o` as `s.text` without weight, size 56. Double the backslashes in JS: `"\\frac{a}{b}"`. Bad LaTeX is an error |
| `s.arrow(s.ctx, x1, y1, x2, y2, p, color)` | an arrow on the 2D canvas that grows from (x1, y1) to (x2, y2) as p goes 0 to 1 |
| `s.ctx` | the 2D canvas (the Canvas 2D API, in pixels) for lines, dots and boxes; set its styles every frame |
| `s.three` | `{scene, camera, renderer}` |
| `s.colors` | `bg` #0e1117, `blue` #58C4DD, `yellow` #FFFF00, `green` #83C167, `red` #FC6255, `text` #ECECEC |
| `s.W`, `s.H`, `s.length` | 1920, 1080, this scene's length in seconds |

Each text or formula `id` is one element for the whole video: give every thing its own id (the same id in a later
scene is the same element with new words).

## The worked example

Two scenes: a title and a turning cube, then the attention formula with two labelled arrows.

```
save_video_page(page="""<the whole page below, as one string>""")     ->  {"page_file": "page-1", …}

make_video(
  title="How attention works",
  narration=[
    "Here is how attention works. First, each word in a sentence becomes a vector: a point in space, written as a list of numbers.",
    "Then one formula does the work. Q times K transpose, over the square root of d, then a softmax, says how much each word listens to every other word. Multiplying by V gives what it hears: a new vector.",
  ],
  page_file="page-1",
)
```

The page:

```html
<script>
// A two-scene explainer page against the kit (video.js). Each draw(t, s) is a pure function of t, the seconds into
// its scene; s.length is that scene's length, set by its narration. Colour means one thing throughout:
// blue = the vectors (the cube), yellow = what we point at, green = the result.
Video.scenes([
  {
    // Scene 1: a title written in, and a blue cube that grows in and turns half a turn across the scene.
    setup(s) {
      const box = new THREE.BoxGeometry(2.4, 2.4, 2.4);
      const faces = new THREE.MeshStandardMaterial({
        color: s.colors.blue, roughness: 0.5, transparent: true, opacity: 0.85,
      });
      const edges = new THREE.LineBasicMaterial({color: "#d6f3fb"});
      this.cube = new THREE.Mesh(box, faces);
      this.cube.add(new THREE.LineSegments(new THREE.EdgesGeometry(box), edges));
      s.three.scene.add(this.cube);
    },
    draw(t, s) {
      const grow = Math.max(0.001, s.at(t, 0, 0.8));
      this.cube.scale.setScalar(grow);
      this.cube.rotation.set(0.45, s.at(t, 0, s.length) * Math.PI - 0.6, 0);
      this.cube.position.y = -0.3;
      s.text("title", "How attention works", {
        y: 150, size: 84, weight: 600, write: s.at(t, 0.2, 1.4), opacity: s.fade(t, 0.2),
      });
      s.text("caption", "Each word becomes a vector: a point in space", {
        y: 940, size: 42, color: s.colors.blue, opacity: s.fade(t, 1.0),
      });
    },
  },
  {
    // Scene 2: the attention formula written in, then arrows growing to its two halves from what they mean.
    draw(t, s) {
      s.tex("formula", "\\text{softmax}(QK^T/\\sqrt{d})V", {y: 420, size: 96, write: s.at(t, 0, 1.4)});
      s.text("weights", "how much each word listens", {
        x: 300, y: 840, size: 44, align: "left", color: s.colors.yellow, opacity: s.fade(t, 1.0),
      });
      s.arrow(s.ctx, 560, 800, 860, 545, s.at(t, 1.2, 2.0), s.colors.yellow);
      s.text("result", "what it hears: a new vector", {
        x: 1620, y: 840, size: 44, align: "right", color: s.colors.green, opacity: s.fade(t, 1.8),
      });
      s.arrow(s.ctx, 1400, 800, 1440, 545, s.at(t, 2.0, 2.6), s.colors.green);
    },
  },
]);
</script>
```

A real video has 5–12 scenes of about 20 seconds each, so spread each scene's reveals across `s.length` as its words
go, and keep something moving to the end (as the cube's half turn over `s.length` does).

## Style (3Blue1Brown)

- The kit's dark background and colours. **Colour means one thing throughout the video:** pick, say, blue for the
  inputs, yellow for what we point at, green for results, red for costs or errors, and keep to it.
- **One idea per scene,** built up step by step in time with the words: each thing appears as it is said.
- **Show, then name:** draw the thing first, then its label or formula.
- **Motion in every scene, all through it:** a slow turn, a growing arrow, a counter, a camera drift. A still
  picture for twenty seconds is a failure.
- **Move the camera slowly** (eased, over several seconds); never jump.
- **Few words on screen:** a title or short labels (at most about 8 words), never the narration's sentences.
  Formulas with `s.tex`.
- **Readable at 1080p:** labels at least 40 px, titles 72–96 px, formulas 64–110 px; about 100 px of margin; nothing
  overlaps. Fade out what is done (`s.fade` with outAt) before the next thing takes its place.

## If make_video reports a problem

`{"error": …}` names one problem (scenes count from 1; `t` is seconds into that scene). Fix exactly that, keep the
rest, and call `make_video` again with the whole narration; a page problem: save the fixed page first and pass its
new name. If it says there's no browser, tell the user
what it says.
