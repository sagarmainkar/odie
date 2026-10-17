# Explainer video kit: vendored libraries

- three.js 0.158.0 (npm `three@0.158.0`), MIT. `three.min.js` (UMD build, global `THREE`); licence in `three.LICENSE`.
- KaTeX 0.16.11 (npm `katex@0.16.11`), MIT. `katex.min.js`, `katex.min.css` and `fonts/*.woff2` (its woff2 files only); licence in `katex.LICENSE`.

## Map data (`geo/`)

`geo/land.json`, `geo/countries.json`, `geo/states-in.json` and `geo/places.json` are made from [Natural Earth](https://www.naturalearthdata.com/), which is in the public domain ([terms of use](https://www.naturalearthdata.com/about/terms-of-use/)), by `scripts/geo/build_geo.py` (fetched 17 October 2026): land at 1:50m (v4.1.0); countries from Natural Earth's "India point of view" file, `ne_10m_admin_0_countries_ind` (v5.1.1, made only at 1:10m), so borders are drawn as India draws them; India's states and union territories at 1:10m (`ne_10m_admin_1_states_provinces`, v5.1.1), which is Natural Earth's admin-1 as each country administers it, except Jammu and Kashmir and Ladakh, which are drawn as India draws them: the administered pieces joined with the rest of India's India-view outline (Azad Kashmir into Jammu and Kashmir; Gilgit-Baltistan, Siachen, Shaksgam and Aksai Chin into Ladakh); and the populated places, `ne_10m_populated_places_simple` (v5.1.2), as the gazetteer. Shapes are simplified (Douglas–Peucker) and rounded to 3 decimals to keep the four files under 3 MB together; there are no historical borders.
