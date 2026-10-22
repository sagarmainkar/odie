# Explainer video kit: vendored libraries

- three.js 0.158.0 (npm `three@0.158.0`), MIT. `three.min.js` (UMD build, global `THREE`); licence in `three.LICENSE`.
- KaTeX 0.16.11 (npm `katex@0.16.11`), MIT. `katex.min.js`, `katex.min.css` and `fonts/*.woff2` (its woff2 files only); licence in `katex.LICENSE`.

## Map data (`geo/`)

`geo/land.json`, `geo/countries.json`, `geo/states-in.json` and `geo/places.json` are made from [Natural Earth](https://www.naturalearthdata.com/), which is in the public domain ([terms of use](https://www.naturalearthdata.com/about/terms-of-use/)), by `scripts/geo/build_geo.py` (fetched 17 October 2026): land at 1:50m (v4.1.0); countries from Natural Earth's "India point of view" file, `ne_10m_admin_0_countries_ind` (v5.1.1, made only at 1:10m), so borders are drawn as India draws them; India's states and union territories at 1:10m (`ne_10m_admin_1_states_provinces`, v5.1.1), which is Natural Earth's admin-1 as each country administers it, except Jammu and Kashmir and Ladakh, which are drawn as India draws them: the administered pieces joined with the rest of India's India-view outline (Azad Kashmir into Jammu and Kashmir; Gilgit-Baltistan, Siachen, Shaksgam and Aksai Chin into Ladakh); and the populated places, `ne_10m_populated_places_simple` (v5.1.2), as the gazetteer. Shapes are simplified (Douglas–Peucker) and rounded to 3 decimals to keep the four files under 3 MB together; there are no historical borders.

## Brand kits (a skill's own look)

A user skill can give its videos a fixed look: `make_video(..., brand_kit="<skill>")` reads
`~/.odie/skills/<skill>/assets/brand/` (nowhere else), copies it into the video's folder and records its version.
The writer then calls the kit's functions instead of drawing its own, so the branded parts come out the same whichever
model writes the video. The format is in `odie/video/brand.py`; in short:

- `brand.json`: `name`; `api_doc` (the functions the writer may call, in words); `sounds` (`{"ting": "ting.wav"}`,
  16-bit WAVs; one with a built-in's name replaces it in that video); `bookends` (fixed scenes: `handoff` just before
  the timed segment, `ending` right after it, `card` at the very end, each `{"seconds": 2.5}`, with `"says": "<var>"`
  to speak a line and `"sounds": [{"at": 0.4, "name": "ting"}]`); `background` (true when the kit draws it);
  `character` (its name under `Brand`, drawn by the stage through the whole timed segment); `moves`
  (`{"bounce": 0.6}`, the moves the writer may cue on it); `vars` (`{"intro": "what the line is"}`, the words the
  writer gives the bookends).
- `brand.js`: plain JavaScript, no imports and nothing from the network, setting `window.Brand` with
  `background(ctx, t, w, h)` (t: seconds into the video), `bookend(name, ctx, t, w, h, vars)` (t stops at the
  bookend's seconds, so a longer bookend holds its last frame), and the character's `draw(ctx, t, w, h, info)` (t:
  seconds into the timed segment; `info` has `left`, the segment clock, `moves`, each `{name, t, seconds}`, and
  `safe`) and `timer(secondsLeft)` (called every frame the clock runs). The page freezes `Brand`, so keep the kit's
  own state in its variables, not on `Brand`.
