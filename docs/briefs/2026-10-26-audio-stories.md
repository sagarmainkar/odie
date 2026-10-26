Build **audio stories** in this repo: a dramatised, immersive story the user listens to, with a narrator, character voices, ambient sound, effects and music, delivered as **one finished audio file**. Work on a new branch `audio-stories` cut from `origin/main`, test-first, one commit per item below (six items). Then push the branch and open a pull request against `main`. Do NOT merge, tag or release. A reviewer on the owner's Mac will verify it live (your environment has no iMovie and no real voices) and close the PR.

## Why (what happened, and what the owner wants)
On 26 Oct the owner asked Odie for "a nice audio story for 10 mins… an immersive experience". Odie improvised it:
- It called the `speak` tool once per scene. Every `speak` call posts its own voice memo under the reply, so the owner got 13 intermediate pieces; he wants only the finished product.
- It chose voices without asking him.
- It stitched scenes and iMovie sounds with hand-written ffmpeg shell scripts, picking volumes itself. The ambience came out too loud and overpowered the narration.

The result was promising ("I have cracked how to create a nice dramatization"), but nothing was consistent, and the model carried the whole technical load. The owner wants:

- **One finished file.** Never intermediate pieces.
- **A guided, quick start**, using the chat **forms** shipped in 0.2.34 (the `form` block in `odie/blocks/catalog.json`):
  1. Odie asks the **genre**.
  2. It offers **story options** for that genre.
  3. It proposes a **cast** (narrator plus characters) that the user keeps or overrides, voice by voice. Odie uses **character voices** when they add impact. The accent comes first, to keep it simple: **British or American** on Phonon, **Indian** too on Kokoro and on OpenAI.
  4. It asks the **length**.
- **The narrator** can be someone in the story (telling their own experience) or an outside storyteller.
- **A prelude.** The narrator sets the scene before the story starts, e.g. "An early-morning bazaar in Shimla… (crowd murmur rises) …and a cold mist (wind)…", or simply sets the context. It should be creative.
- **Scenes and transitions.** "Super cool storytelling effect."
- **Sound chosen like a creative art director.** A horror story gets owls and dry leaves whooshing, chosen with intelligence rather than at random. "If I listen I need to feel the atmosphere and setting."
- **Ambience serves the speech.** Ambient beds sit at about **25–30%**, so they create atmosphere without overpowering narration or dialogue.
- **Consistency, and less load on the model.** The model does the creative work (story, cast, cues) and Odie's code does the audio work, the same way every time.

## Decided (binding)
- Audio stories are a new **making kind**, like podcasts and videos (`odie/making/jobs.py` `KINDS`, `BUILT_IN_KINDS`):
  - a **writing step**, the only model call: a focused writer turn producing a structured script;
  - a **making step**, plain code: speak every line, place and mix the sounds, master, save one file.
  - The user gets one player in the chat when it's ready, with a ping like the other makers.
- A new **skill**, `odie/skills/audio-story/` (SKILL.md and tools.py, following `odie/skills/podcast/`). It teaches the chat model the guided start with forms and gives it one tool, `make_audio_story`. The skill says plainly that the model never uses `speak` to build a story and never stitches audio in the shell.
- **Sounds come from the user's Mac, never from the repo.** Odie never copies, uploads or redistributes them.
  - It reads the sounds installed with iMovie on the user's Mac (`/Applications/iMovie.app/Contents/Resources/`):
    - `iLife Sound Effects/<Category>/*.caf`: 418 files in 13 categories. Ambience, Animals, Booms, Foley, Jingles (200 music beds in Long/Medium/Short cuts), Machines, People, Sci-Fi, Sports, Stingers (53), Textures, Transportation, Work - Home.
    - `iMovie Sound Effects/*.mp3`: 95.
    - `iMovie Theme Music/*.m4a`: 7.
  - Also an optional **folder of the user's own sounds**: `<ODIE_HOME>/sounds/`, any subfolders as categories.
  - On a Mac without iMovie, the story still works. It falls back to Odie's own synthesized kit sounds (`odie/video/kit/sounds/`, CC0, already in the repo), and the skill tells the user once: "For richer sound, install iMovie (free in the App Store); Odie uses its sound library."
- **Voices come from the engine chosen in Settings** (Phonon, Kokoro or OpenAI), as everywhere else today (`voice.voice_in_chosen_engine`). Mixing engines in one story is a separate, later piece of work. Leave a clear seam for it, but don't build it.
- **Levels and mastering are code, not model choices.** The model can say "low / normal / up front" for a cue, but the dB numbers are constants in code (see Item 4).
- **The output is one file, in a story player.** The podcast card (`web/src/components/Podcast.tsx`, `web/src/media.ts`) is the right base, but it doesn't fit as it is:
  - its transcript key is `host`;
  - it always says "Podcast" / "Play podcast";
  - it has two avatar tones (`HOST_TONES`).

  **Extend it (web work is in scope):**
  - save with `odie.media.save` as kind `"podcast"`, with a `meta.format: "story"` (or a new media kind if that reads cleaner: your call, say why);
  - transcript entries keep the existing `{host, text, start}` shape, where `host` is the speaker's display name ("Narrator", "The keeper");
  - the card says "Audio story", and the play button "Play story";
  - tones cycle for casts of up to ~8 speakers;
  - the cast's voices are listed.

  Keep the podcast card unchanged for podcasts (its tests stay green). Prefer **AAC in .m4a** (an 8-minute WAV is ~21 MB) when the web player and the phone play it (check the media serving: it already answers byte ranges). Otherwise WAV.

## Working rules (binding)
- Read CLAUDE.md first and follow it: plain named steps a person can follow on the first read. Every decision function (predicates, guards, `is_*` / `should_*`, problem-checkers, pickers) gets a comment saying in words what it decides, with a concrete worked example (input -> outcome).
- TDD: failing test first, see it fail for the right reason, minimal code, see it pass.
- Before the PR: `TZ=UTC uv run pytest -q` (CI runs on UTC), and in `web/` `npm ci && npm run lint && npx vitest run && npm run build` if you touch the web.
- Tool docstrings and signatures are in the golden prompt files: regenerate them with `uv run python -m tests.golden_render --write` and review the diff.
- Tests never touch a real `~/.odie` (`isolated_settings`) and never call a real voice engine or model. Use `httpx.MockTransport` for the voice, as `tests/test_voice_phonon.py` does, and the existing fakes for writer turns: see the podcast and video writer tests, `grep -rn "podcast_writer\|def test_.*writer" tests`.
- Sound tests use a **fake library**: a temp folder laid out like iMovie's, with tiny generated WAVs (and a `.caf`, which the bundled ffmpeg reads). ffmpeg is always present (imageio-ffmpeg), so no skip is needed. Never read `/Applications` in a test.
- Commits: the author is the repo owner (git is configured). End every commit message with exactly one trailer line, `Co-Authored-By: <the Claude model you are> <noreply@anthropic.com>`, and nothing else. Never `--no-verify`. The pre-push leak scan refuses private words and the owner's name: use neutral names in fixtures and examples.
- Don't carry the briefs folder into the `audio-stories` branch.

## What exists to build on (read these first)
- **Making jobs:** `odie/making/jobs.py` (Kind, Job, submit/run/tell, `recover`, the `ready_message`), `odie/making/podcast.py` (write step → making step → `media.save`), and `odie/making/podcast_writer.py` with `podcast_writer.md` (a focused writer turn with its own prompt file).
- **The podcast tool and skill:** `odie/skills/podcast/tools.py` `make_podcast`, which validates and returns at once with `{"result"}` or `{"error"}`, plus `odie/making/chat.py` helpers (minutes, brief, sources) and `odie/making/sources.py`.
- **Speaking lines in voices:**
  - `odie/video/narrate.py` `narrate_dialogue`: every line on its own in its speaker's voice, `lead_cut`/`tail_cut`, pauses, grouped by voice, `speak_all`;
  - `voice.speak_wav`, `voice.voice_in_chosen_engine`, `voice.engine_voices(engine, store)`;
  - the voice groups and notes: Phonon's catalogue in `odie/voice_phonon.py` (American / British × female / male, and Characters: "Captain Silas Blackwater", "The Snow Queen", "Old Mortlake", "Morwenna of the Deep", "Fairy Godmother", …); Kokoro's `KOKORO_VOICES` with `note` American / British / Indian; OpenAI's `VOICES`.
  - OpenAI voices have no fixed accent, but `speak_wav(style=…)` passes instructions (see `narrate.py` `style`). An "Indian English" accent on OpenAI is a style line.
- **The script format for dialogue:** `odie/video/dialogue.py` (scenes, `SPEAKER: text`, `[pause N]`, the narrator).
- **Sound placement and mixing for videos:** `odie/video/sounds.py`. It has hits vs loops, cues placed at a scene and beat, `resolve`, `cue_gain`, `play_seconds`, the loudness helpers, one ffmpeg mix, and `cue_problem` checks. Reuse what fits. Don't fork it blindly: an audio story has longer beds, crossfades between scenes, and music.
- **Forms:** the `form` block (`odie/blocks/catalog.json`, `web/src/blocks/parse/form.ts`). The user's answer comes back as a message with an `odie-form-answer` block, read by field id. A select option may carry `preview: "/api/voice/preview/<engine>/<voice id>"`, which gives it a ▶.
- **Media:** `odie/media.py` (`save`, `join_wavs`, `wav_info`, KINDS).

## Item 1: the sound library (`odie/making/sound_library.py`)
- `find_libraries()` decides which folders exist, in order: iMovie's three folders, then `<ODIE_HOME>/sounds/`. Each path is a constant at the top, so another Mac layout is a one-line change.
- `catalogue()` builds one entry per sound: `{id, name, category, kind, seconds, path, variants}`.
  - `id` is stable and readable, e.g. `"ambience/ocean-surf"` or `"jingles/acoustic-sunrise"`.
  - `kind` is one of `loop` (beds that can run under a scene: Ambience, Textures, most Transportation, Machines and People crowds), `hit` (Stingers, Booms, Foley, Animals calls, short effects), or `music` (Jingles, Theme Music).
  - Decide by category, then by name and length (a 60 s "Night Camp" is a loop; a 2 s "Bark" is a hit). Put the rule in one decision function with worked examples, and put overrides in a small table.
  - Jingles' "Long/Medium/Short" cuts collapse into one entry with `variants`.
  - Durations are read once (see below).
- `<ODIE_HOME>/sounds/`: when `Layout.home` is `None` (`ODIE_DATA_DIR` or `ODIE_CONFIG_DIR` set without `ODIE_HOME`, see `odie/home.py`), use `<data_dir>/sounds/` instead.
- **Durations:** there is no ffprobe (ffmpeg comes from the `imageio-ffmpeg` package, a dependency). Read durations with `odie/video/encode.py` `probe()`, as the video code does.
- **Cache** the catalogue as JSON in Odie's data dir, rebuilt when a library folder's file list or mtime changes. Building it must not slow Odie's start: build it lazily, the first time a story needs it.
- `writer_listing(catalogue)`: the compact text the **writer** reads to choose sounds, grouped by category, one short line per sound (`id` · seconds · loop/hit/music). Measure it and keep it under about 4,000 tokens. If the full library is bigger, include the most useful categories in full and summarise the rest. Test the budget.
- **Fallback:** without any library, the catalogue is the video kit's sounds (`odie/video/sounds.py` `SOUNDS`), so the writer can still place rain, footsteps, wind, whoosh and the rest. The kit has no music, so such a story has no music beds: the writer's listing says so.
- **Licence note** (docs and a comment): Odie uses sounds from the user's own iMovie install. It never copies them into the repo and never uploads them anywhere. The finished story is the user's file, and sharing it is their choice (the card keeps its Share button).
- Tests (fake library): category to kind, variants collapsed, the cache rebuilt on change, the listing's shape and budget, the fallback.

## Item 2: the guided start (the skill and its forms)
`odie/skills/audio-story/SKILL.md`, short and concrete. `description` triggers on: "audio story", "radio play", "audio drama", "story to listen to", "bedtime story (audio)". The flow, each step **one form** (the user can always just type instead):
1. **Genre:** a radio or select of about 10–12 options with a one-line note each: horror, mystery, thriller, adventure, fantasy, sci-fi, romance, comedy, true story (history), mythology and folk tales, bedtime (kids). Include a text field "or your own idea". If the user's first message already gives a genre or a story, skip this step.
2. **Story options:** three short pitches for that genre, each a one-line logline as a radio option with a note, plus "your own idea" text. *(The owner said "it gives me some options to choose from"; three pitches is the design's reading. Keep it easy to change in the skill text.)*
3. **Cast and shape**, in one form:
   - **accent world**: a radio from what the chosen engine offers:
     - Phonon: American, British;
     - Kokoro: American, British, Indian;
     - OpenAI: American, British, Indian, as a style line;
   - **narrator**: a radio between "a character tells it" and "an outside storyteller", then the narrator's voice;
   - **each character**: a voice select prefilled with Odie's suggestion. The options are that engine's voices for the accent, plus Phonon's **Characters** group when a character voice adds impact (a pirate captain, a witch, an old keeper). Every option carries its `preview`, so the user can hear it.
   - **length**: radio, 3 / 5 / 8 / 10 / 15 minutes;
   - **sound level**: slider 10–40 %, default 25 %.
   - Keep it at 12 fields at most (the form's limit). For a large cast, cast the main characters and let minor ones share a voice.
4. Then call `make_audio_story` once. Say in one or two lines that it's being made. **Don't** speak samples or scenes with `speak`.

Phonon's voices are known only after the async `voice.phonon_voices()` has asked Ollama (before that, `engine_voices("phonon")` is just "default"), so the helper awaits it first.

On OpenAI the ▶ preview plays the voice without the accent, because previews don't take a style line. Say so in that option's note ("accent added in the story"); don't build accent previews.

Where the voice list comes from: the skill's tool should expose a small helper the model can call to get **the cast-ready voice options** for the chosen engine and accent, already shaped as form options with `preview` paths and notes. That way the model doesn't hand-build 40 options or guess voice ids. Design it as a second tool (`story_voices(accent)`) or as part of the skill text generated at load. Pick the simpler, say which in the PR, and test it.

Tests: the tool helpers (voice options per engine and accent, previews URL-encoded, the Characters group present only on Phonon), and the skill loads. If the repo has skill-trigger tests, one case for "make me an audio story".

## Item 3: the writer (the creative director)
`odie/making/story_writer.py` and `story_writer.md`, following `podcast_writer`. The writer gets:
- the brief from the chat: genre, the chosen pitch or idea, the cast (who, the voice id, a one-line who-they-are, narrator inside or outside), the accent, the length;
- the **sound listing** (Item 1).

It returns a **structured script** that Odie's code can check and render. Suggested JSON, which you may refine:

```json
{"title": "The Lighthouse at Rook Point",
 "cast": [{"id": "narrator", "voice": "Fairy Godmother"}, {"id": "keeper", "voice": "Old Mortlake"}],
 "scenes": [
  {"title": "Prelude", "bed": {"sound": "ambience/ocean-surf", "level": "normal"},
   "music": {"sound": "jingles/borealis", "level": "low"},
   "lines": [
     {"sound": "animals/seagulls", "level": "low", "lead": 3.0},
     {"speaker": "narrator", "text": "Rook Point. The last light on the coast…", "pause_after": 1.2},
     {"speaker": "keeper", "text": "Another storm coming. I can smell it.", "sound_after": "foley/door-creak"}
   ],
   "transition": {"kind": "crossfade", "seconds": 2.5}}
 ]}
```

- **Words to time:** about 140–150 spoken words a minute, plus the prelude and transitions, should land within ±10 % of the asked length. Check it in code.
- **Refusals:** the writer harness (`odie/making/writer.py`) refuses up to 3 times and then fails the job. Use that for problems that make a script unrenderable: an unknown speaker, an unknown sound, two beds in a scene. For **length only**, refuse once, then accept with a note in the job. The harness has no accept-with-note path, so add one small, clearly named path for the story writer; don't change the other writers.
- **The prelude is required:** sound first (2–6 s), then the narrator sets the place, time and mood. Each later scene opens on its bed. The writer chooses beds, hits and music for the atmosphere (the art director's job). The prompt says so with two or three short genre examples: horror gets distant owls, dry leaves, a door; a bazaar gets a crowd murmur, a temple bell, rain on a tin roof. It must never stack more than one bed and one music bed at a time.
- **The narrator** inside the story speaks in first person, as that character, in that character's voice. An outside narrator is a storyteller voice.
- `check_script(script, catalogue, cast)` decides whether a script can be rendered:
  - every speaker is in the cast and every sound id exists;
  - the levels are known words; at most one bed and one music bed per scene;
  - pauses are within limits;
  - the length is right.

  It is a decision function: comment it with worked examples, and return problems in words the writer can fix (the video writer's `cue_problem` style).
- Tests: a fake writer turn returning a good script, and bad ones (unknown sound, unknown speaker, two beds, too short), each giving its problem in words; the retry once.

## Item 4: the making step (render and master)
`odie/making/story.py` registers the kind `"story"` (folder `<workspace>/stories/<slug>/`, its job.json and brief.md), like `podcast.py`:
1. **Speak** every line in its speaker's voice, reusing `narrate_dialogue`-style helpers: `speak_all` grouped by voice, `lead_cut`/`tail_cut`, the `style` line for OpenAI accents. Keep each line's start time for the transcript.
2. **Lay out** the timeline: scene by scene, the lines with their pauses, each scene's lead-in for its bed, and transitions.
3. **Mix** with one ffmpeg graph per story (or per scene, then joined; your call):
   - **The loudness reference (decided):**
     - before any gain, every bed and music file is **matched to the speech's loudness**: measure the spoken track's RMS/LUFS and bring each bed to the same level (the video code brings loops to a fixed RMS first; same idea, but referenced to the speech);
     - then the **sound level** is a plain gain on that matched bed: 25 % → −12 dB below speech, 10 % → −20 dB, 40 % → −8 dB;
     - the slider's range is **10–40 %** (default 25 %), not 50: beds louder than −8 dB under speech were the owner's complaint;
     - so iMovie's hot jingles and quiet ambiences come out at the same, predictable place.
   - **Beds** loop seamlessly under their scene, with a fade-in of 1.5 s and a fade-out into the transition. Under speech they sit at the sound level. Between lines and in the prelude they may rise by up to +6 dB, never above −4 dB under speech. Use ducking with a smooth sidechain or envelope, so they never pump.
   - **Music beds** sit 4 dB below the ambience level and also duck under speech.
   - **Hits** play once at their place. "low / normal / up front" map to fixed gains (e.g. 0.3 / 0.5 / 0.8 of full scale). A hit never overlaps the start of a spoken word: shift it to the gap if needed.
   - **Transitions:** a crossfade (2–3 s), a stinger, or a short silence, as the script says.
   - Every level is a named constant at the top of the module, with a comment.
4. **Master:**
   - convert every source to one format (48 kHz stereo, or 44.1 kHz; the voices are 24 kHz mono, so upsample);
   - normalise the whole story to about −16 LUFS (ffmpeg `loudnorm`, two passes if simple enough), with a true-peak limit near −1.5 dBTP;
   - **then measure**: speech must stay above the beds by what the slider promises. Compute the beds-only loudness against the speech-only loudness under the same lines. The gap should be within about 2 dB of the slider's dB (25 % → about 12 dB). Test it at 10 %, 25 % and 40 % on the fake library, and log the measured gap with the job.
5. **Save one file** in the story player (Decided section: the podcast card extended for stories, with vitest cases for the label, the speaker names and tones beyond two) with a transcript `[{speaker, text, start}]` and the cast (name, voice) in its metadata, like the podcast player. **Nothing else is posted to the chat**: no per-line or per-scene media, ever.
6. Errors in one line, like the podcast: a voice that doesn't answer, or a missing or unreadable sound file (skip that cue, with a log line; the story is still made).

Tests: the timeline from a small script with fake voice WAVs (MockTransport); the placement rules (hits moved off word starts, at most one bed); the ffmpeg command or graph built (assert its pieces, don't snapshot a giant string); the mastering and loudness gap on a short render (skip if no ffmpeg); exactly one `media.save` call per story and no other media.

## Item 5: the tool, and making `speak` not the way
- `make_audio_story(title, genre, premise, cast, narrator, accent, minutes, sound_level, brief)` in the skill's `tools.py`. Shape the `cast` argument as you see fit: a list of `{id, name, voice, about}`.
  - It validates in words (`{"error": …}` the model can fix): an unknown voice, too many characters, minutes outside 2–15, a sound level outside 10–40.
  - It submits the job and returns `{"result"}` at once.
- The `speak` tool's docstring (`odie/agent/tools/media.py`) today invites the old behaviour. It tells the model the result's path is "for a skill to use, e.g. with ffmpeg", and to "split longer narration into several memos". Reword it:
  - `speak` is for one short memo;
  - for a story, radio play or anything with several voices, sound or music, use `make_audio_story`, never several `speak` calls stitched together;
  - keep the path sentence for skills: `odie/skills/skill-builder/SKILL.md` relies on `speak` for narration, so check that skill still reads right.

  Regenerate the golden files.
- A short mention in the about-Odie text, if that's where the makers are listed (`odie/about.py`).

## Item 6: docs
- A short `docs/audio-stories.md`:
  - what it does, and the guided start;
  - where sounds come from: iMovie on the Mac, free in the App Store, or your own `~/.odie/sounds` folder, with the kit fallback;
  - the licence note;
  - the levels (ambience at about a quarter under speech);
  - how to ask ("make me a 10-minute horror audio story").
- One line in the README's list of things Odie makes.

## Not in scope
- Mixing voice engines in one story (later; leave the seam).
- The Mac app (its player plays what the server saves; if it can't play .m4a, say so).
- Video.
- Downloading sounds from the internet.
- Editing a finished story (a new request makes a new one).

## PR description
- What changed, per item.
- The script JSON you settled on: paste one full example.
- The level constants and the measured speech-to-bed gap.
- The output format and media kind, and why.
- The writer listing's token count.
- Test counts.
- Everything you decided that this brief left open (list them).
- What you could not try: real voices, iMovie sounds, the phone player. The reviewer will run a real story on the owner's Mac.
