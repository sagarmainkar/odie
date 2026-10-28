# Changelog

## v0.2.35 (2026-10-28)

- Choose how often Odie updates meaning, or turn it off: Settings → Notes → "Update meaning in the background" offers Off, or every 5, 10, 15, 30 or 60 minutes (5 as before). Only reading new notes and pictures by meaning follows it, since that is what loads the embedding model; keyword indexing and Photos library reads go on as before. Off forgets nothing: the Notes row says how many passages wait, the Photos row says picture meaning is paused, and turning it back on catches up at once. Searches still read by meaning while it's off, so notes written in that time are found by meaning once it's back on. A note Odie writes to memory is found by keyword at once, and by meaning at the next update.
- Audio stories in the chat: the podcast card plays a story made by a skill, with its cast and their voices, a drawn face and a colour for each speaker, a teaser and who's who before it plays, the speaker's name on top while they talk, and the line being said under the faces. User skills can add their own background job kinds, and such a job cut off by a restart is reported in its chat. Forms that offer voices get their ▶ previews even when the model left them out.
- Photos sent from the phone are shrunk there first (1280 px, the size Odie keeps anyway) and sent together, so several photos go in a moment instead of one slow upload after another.

## v0.2.34 (2026-10-26)

- Forms in chat: when Odie needs several answers from you (it is unsure what you mean, it is brainstorming with you, or it is gathering choices before making something), it can ask with a small form in its reply: dropdowns, radio buttons, checkboxes, text boxes and sliders, filled in with its best guesses. Press Send and Odie gets each answer by name; the form stays greyed with your choices, and your message shows them in one line. Works in the web app and on the phone; the Mac app catches up later.

## v0.2.33 (2026-10-26)

- A new voice: Phonon through Ollama. With `ollama pull phonon` (113 MB), Odie reads replies aloud through Ollama on this computer and nowhere else, and recommends it in setup and Settings. Its 37 English voices are grouped (American and British, female and male, and characters) with a line about each and a preview; "Another voice" tries a name you type against every Phonon model you have (French, German, Spanish and Portuguese voices need another model, e.g. `ollama pull phonon:fr`). Long replies are read in full.
- Odie's own voice server (Kokoro) now runs only while Kokoro is the chosen voice: one process less with Phonon or OpenAI. Kokoro and OpenAI stay as choices.

## v0.2.32 (2026-10-26)

- Five small fixes: the location ask above the composer lines up with it on a desktop; Settings → Location shows the place, then "seen · home", then its note in full width on a phone; Turn on there fetches a fix at once; a `.local` address passes Odie's Host check only when it is this Mac's own name or one you listed in `ODIE_HOSTS`, so a stranger's `.local` page on the same network can't reach Odie; Settings no longer goes blank when there is no voice engine at all.

## v0.2.31 (2026-10-26)

- Dialogue videos with 3D characters: give a character in your cast sheet `asset: models/<name>.vrm` (a VRM made free in VRoid Studio, or from VRoid Hub) and it appears as that 3D character, lip-synced to its own voice, blinking and moving; speakers without one are drawn as before, and videos without 3D characters are unchanged. See docs/dialogue-videos.md.
- The reminder pop-up in the web and phone app offers Dismiss and Snooze (1 hour, 3 hours, tomorrow 9:00) instead of Act.
- Needs you cards also say which pile they belong to (alerts, bills, events, personal, orders), since when, and whether they need your own choice, with counts per pile, for the Mac app's new glass buckets. The web app is unchanged.

## v0.2.30 (2026-10-25)

- Where you are: with your permission, asked once per device, the web app and the Mac app tell Odie the place you're at when they open; Odie keeps the latest place with its time and learns your home from where you spend nights, and puts the place name (never coordinates) into what it sends to your chat model, so weather, nearby and travel questions work unasked. Settings → Location turns it off or forgets it. Turning a point into a name asks OpenStreetMap only when no recent point nearby is known.

## v0.2.29 (2026-10-25)

- Odie's own embedding service (EmbeddingGemma 2 in PyTorch, `embed_server/`) is no longer built or offered by default: install with `ODIE_EMBED=on` to have it. EmbeddingGemma 2 on Ollama (`ollama pull embeddinggemma-2`) reads notes and pictures the same way, with no download and no process of Odie's own; setup and Settings recommend it when found.

## v0.2.28 (2026-10-25)

- Search by meaning: setup and Settings → Notes offer "A server somewhere else" (Ollama at its root address, or LM Studio, llama.cpp and any OpenAI-style server at its /v1 address): type the address, Find models, pick one; Odie checks it with one real embedding before saving and asks an Ollama server whether the model reads pictures. The choices now run from what is already running here (a picture-reading Ollama model is recommended), to a server elsewhere, to OpenAI, to Odie's own download last.

- Security review (24 Oct 2026), fixes: a request must name an address Odie owns (`Host`; an unknown name gets 421, so a page can't reach Odie by DNS rebinding), and a change or a live-view WebSocket must come from Odie's own page (`Origin`). Adding an app refuses a shell, inline code or a hooked env as the server, before running it even to list its tools. An app's tool runs without a tap only when *you* switch "Reading doesn't need a tap" on and its name says it reads; a server's own read-only hint frees nothing. "Allow for 30 min" approves the one card tapped, and sees through the ways a command hid what it did (piping decoded text into a shell, globbing around a secret's name, writing files or sending data from inline code, installing packages). Saving a *Watch for* entry asks for a tap. Once a chat has read your mail, notes, memory or messages, a web search, a fetch, another site or a cloud voice asks first, as after a signed-in page. The background watch stays off the web once a check has read mail, except addresses you wrote in a Watch for entry. The app's update button installs exactly the version it showed you. See SECURITY.md.
- After an independent review of these fixes (25 Oct 2026): the MCP command check looks through wrappers (`env sh -c`), versioned names (`python3.12`), joined and clustered flags (`-cCODE`, `-Sc`, `--eval=`), `--require`/`--import`, and more hooked env keys; `ODIE_HOSTS` is read from `~/.odie/.env` like every setting and passed to the service, and the 421 page says so; `$HOME/.odie/workspace` is judged like `~/.odie/workspace`; the shell pass also catches `$'…'` quoting, a shell given `$(…)` or `<(…)`, a lower-case `method: 'post'`, a DNS lookup or `open` of a built address, and `uv sync`, while `xargs grep`, `| python3 -m json.tool`, `source …/activate`, `re.compile` and `importlib` no longer ask; SECURITY.md says exactly what marks a chat and which tools then ask.

## v0.2.27 (2026-10-25)

- Long chats: whether a chat has passed its limit is now read from the model's own token count, the same number the ring shows, instead of characters at four a token. A chat of tool traffic and thinking (DeepSeek read one at 3.6 characters a token) could pass 300k on the ring and never be trimmed; now the cut comes when the ring says so. A model whose window the provider hasn't said yet is asked again at the next turn instead of keeping the 50k "can't say" limit for the whole day.
- Pictures by meaning through Ollama: EmbeddingGemma 2 there (`ollama pull embeddinggemma-2`) reads each photo's pixels together with its words, as Odie's own service does, so the memory-hungry service is no longer the only way to search pictures by their look. Setup says which Ollama models read pictures.

## v0.2.26 (2026-10-23)

- Mac apps: an app that isn't running (Calendar, often) is opened in the background and asked again, so Settings → Allow Calendar works and the watch no longer says Calendar isn't working when it's simply closed.
- Experimental, dialogue videos: a cast folder of character sheets (a fixed description used word for word, a voice, ages per act, reference pictures) and a look file keep a work's characters and style the same across videos; `## Act:` lines in the script set each scene's ages, and a still of each speaker is saved to the cast folder after each video. See docs/dialogue-videos.md.

## v0.2.25 (2026-10-23)

- "Allow for 30 min" asks far less: writing in Odie's workspace and your vault, and inline code (python3 -c, a script fed to python3) that doesn't touch secrets, delete anything or send data out, now run under the pass. Text inside quotes or written into a file no longer looks like a command. Reading secrets, deleting, sending data out and writing anywhere else still ask every time.

## v0.2.24 (2026-10-23)

- Odie for Mac: every message Odie says on its own (a tracker that fired, a finished video or deck, a reply that came late after an approval) now says what it is on the live event stream, so the Mac's corner banner shows it; housekeeping lines stay quiet. The mail watch's alerts (an urgent mail, an app that stopped working) also reach the stream, not only the phone.

## v0.2.23 (2026-10-23)

- Experimental: dialogue videos. Give Odie a script you wrote (scenes and `SPEAKER: line` lines, in a note, a file or a message) and a voice for each character: every line is spoken in its character's voice, the characters' mouths move with their own lines, the line shows as a caption, and a timeline.json (every line's time and voice) is kept next to the video. See docs/dialogue-videos.md. Videos without a script are made exactly as before.

## v0.2.22 (2026-10-23)

- Videos: Odie knows any video can be 3D (a moving camera, lit objects) and offers it when depth helps; for a planet or a moon it finds the real texture map and the video wraps it on a turning sphere.

## v0.2.21 (2026-10-23)

- Today has one "Needs you" list of cards, refreshed by every mail check, in place of the inbox and To close lists: what the watch found in mail (with its suggested action and a way out) and your own reminders and dues (Done / Tomorrow).
- What the watch did while you were away (its notes, any files it made, the reminders it closed) folds into one line under the cards, with Reopen.
- The Desk conversation is gone: the watch posts into no chat. Urgent mail and an app that stops working are notifications that open Today.
- The morning notification says how many things need you and opens Today; if the computer was off at 07:30 it goes out when Odie starts, until noon.

## v0.2.20 (2026-10-23)

- A word in braces, like {name}, in a Watch for note or memory no longer stops every watch check.
- Things the watch is following are counted once: the morning round no longer lists them again as needing the user, and Today shows a reply the watch flagged once, not also as a task.
- Undoing something the watch closed brings it back still linked to its mail, and the watch only starts following a mail it has actually seen.
- The Desk keeps a name you give it and stays unpinned once you unpin it; the watch's and the morning round's notifications open the Desk.

## v0.2.19 (2026-10-22)

- The watch follows things until they're done: orders, bills, replies the user owes and deadlines become threads it reviews every check (a reply closes when the user's answer is in the thread, or comes back when it's overdue; only bills and deadlines remind at their due date).
- What needs the user is labelled (alerts, bills, events, personal, orders) with one suggested action and one way out, and a drafted reply when one is owed. Sending still takes the user's approval.
- A pinned Desk conversation holds the morning round (a short opener, then cards with buttons), urgent items and what was done, never the user's own chat. Chat can show or close a Desk item.

## v0.2.18 (2026-10-22)

- The mail watch reads like an assistant. It opens a mail whose preview doesn't say what it asks (before, a
  connector's preview was all it ever saw), can read a mail's thread, earlier mail and the user's own sent mail, and
  counts any mail that asks the user for something as a reply owed, even one with an unsubscribe footer. Promotions,
  digests and codes stay quiet. After reading beyond a check's own mail it can't reach the web, and each read has a
  30-second limit.
- A watch eval: made-up mails run through the real watch turn and scored (`scripts/watch_eval.sh`).

## v0.2.17 (2026-10-22)

- Tapping a mail on Today now says which mail app holds it and its id, so chat opens that mail instead of searching
  the wrong app. Chat looks in every connected mail app before saying a mail isn't there, and the memory review no
  longer saves guesses about which tools the assistant has.

## v0.2.16 (2026-10-22)

- Brand kits: when the timed segment is the writer's last scene, the kit's ending now plays before its card. The card
  used to start at the same moment and hide the ending, and the picture ended before the sound. An ending or card
  that speaks a line now has that line in the voice track.

## v0.2.15 (2026-10-22)

- Brand kits: a skill can give its videos a fixed look (`make_video(brand_kit="<skill>")`, a kit in the skill's
  `assets/brand/`): its drawing code, sounds and fixed opening and ending scenes go in as they are, the stage draws
  its background and its character through the timed segment, and the writer draws only the middle. The kit is
  copied into the video's folder and its version recorded; a missing or broken kit is an error. Format:
  `odie/video/kit/README.md`.
- OpenAI's voice is given more time: each clip waits up to two minutes and is tried again after a timeout or a busy
  answer, and a video's phrases are spoken six at a time, so a reel no longer fails when OpenAI is slow.

## v0.2.14 (2026-10-21)

- A video can have one timed segment of exactly N seconds (`make_video(timed_segment_seconds=60)`), with untimed
  scenes before and after it: only the segment's narration is fitted (±10%), and the page's clock counts N to 0 from
  its first word to its last. Vertical is only the frame size now; videos keep their asked length (1–6 minutes).
- The mail watch can write to the calendar app it reads (each check starts with that app's tools), so a bill or an
  order now reaches Google Calendar; its catch-up runs once more. Mail is sorted by when it came, whatever the
  app's date format.

## v0.2.13 (2026-10-21)

- Reels end on the countdown character's blink, never on a credits card: when a reel used web pictures, the chat's ready message
  gives their credits as a line for the post's caption. Reels use web pictures only when the topic needs a real one.
  Longer videos keep the credits card.

## v0.2.12 (2026-10-21)

- One-minute videos (asked at one minute, or any reel): the narration is fitted to exactly 60 s, the video opens
  silent on the question card, and a narration clock (60 at the first word, 0 at the last) drives the countdown character; then a
  blink, a chime and a cut. Longer videos keep their free length.
- The watch keeps bills, payments and orders on the calendar: a bill gets an event and a reminder, a payment for the
  same amount closes it and marks the event paid, an order's event follows its delivery. A one-time catch-up reads
  the last 30 days of such mail. Today shows two weeks of the calendar, paid and delivered items in green, and what
  the watch closed (with Reopen).

## v0.2.11 (2026-10-21)

- Up next: a birthday's or an event's card wears a photo from Photos of the person it names (or of a holiday or thing
  a word names), under a veil in the card's colours, with the kind's drawing kept. No match, no photo.
- Where each card came from is a clear coloured mark on every card: Gmail's M in red, iCloud's cloud in blue.
- Vertical 9:16 videos for Instagram reels: `make_video` takes `aspect` ("insta", "reel", "shorts", "vertical" →
  1080×1920), with safe areas and vertical composition rules for the writer. Landscape frames are unchanged.
- No countdown lead-in: a video opens on its first card and the narration starts at once.

## v0.2.10 (2026-10-21)

- A video can have its own narration style for OpenAI's voice: `make_video` takes `style`, one line up to 300
  characters ("Curious science narrator. Calm, but lift slightly at the payoff."); without one, nothing changes.
  Kokoro is untouched.
- `ODIE_VIDEO_VOICE` pins the voice videos are narrated in, so changing the read-aloud voice leaves videos alone.
- OpenAI's voice models are settings: `ODIE_TTS_MODEL` and `ODIE_STT_MODEL`, so a retired model is a `.env` change.
- Settings → Mac apps no longer offers Contacts (held back for now).

## v0.2.9 (2026-10-21)

- On a Mac, Odie reads Apple Mail, Calendar, Reminders and Contacts directly, with no MCP server: allow each app
  once in Settings → Mac apps. Eight tools (new mail, one mail in full, an attachment saved, events, an event added,
  reminders, a reminder added, people by name); adding asks for a tap in chat. The watch reads the Mac's mail and
  calendar beside a connector's, shows a message or event seen through both once, and badges where each came from.

## v0.2.8 (2026-10-21)

- The mail watch keeps a check's mail for the next check when its model turn times out, instead of marking it
  seen; and it may put a bill's due date or a deadline on the calendar without a tap (`calendar_create_event`).

## v0.2.7 (2026-10-21)

- The WhatsApp chip under replies is gone; Share is the one way out. After a share, a line says when the words
  went alone and why. Pictures are drawn twice for Safari.

## v0.2.6 (2026-10-21)

- A shared reply carries its charts, tables and heat maps as pictures: each drawn piece goes through the share
  sheet as a PNG card with the words as the caption.

## v0.2.5 (2026-10-21)

- Share a reply or a made file to WhatsApp, Messages and the rest: every file, deck, podcast, picture, video and
  sound card has a Share button for the phone's share sheet; under each reply, Share and a WhatsApp chip.
- History lines carry their turn (`inv`), so the Mac app folds a turn's "Let me check…" lines into one answer.

## v0.2.4 (2026-10-20)

- `odie open` right after an install waits for the service's setup link instead of opening a second, blank tab.

## v0.2.3 (2026-10-20)

- `odie install` opens one browser tab, not two: the install's own open waits when the setup link was just opened.

## v0.2.2 (2026-10-20)

- Setup shows a lone choice that needs a key first (OpenAI's voice on an Intel Mac), and "Make a new code" under the
  pairing QR is a button.

## v0.2.1 (2026-10-20)

- The phone step can be finished before the phone is at hand: "Later, from Settings → Phone" keeps the address; the
  pairing code waits in Settings.

## v0.2.0 (2026-10-20)

Things Odie makes while you are away, and a wider door.

- **Explainer videos**: narrated, 3Blue1Brown-style animated films written by a focused writer turn and rendered in
  the background, with real pictures and clips from the web or your own photos, an offline map with flights and
  routes, cuts on the narration's beats, and a small set of sound effects under the voice. Ask with "no sound
  effects" to go without.
- **Podcasts, decks and research in the background**: one queue for everything that takes minutes; a push to the phone
  when it is ready; a revision of a deck by name; research with sources, from the web and your notes; sources for
  every kind. Podcasts are made in any chat, private or not.
- **The one-line install**: `curl … get.sh | bash` on a Mac with macOS 14 or newer. An Intel Mac goes on without the
  two Apple Silicon parts (Odie's own voice and its own embedding service) and the installer says so; neither is
  offered in setup or Settings on such a Mac, and OpenAI's voice is the default there.
- **The phone step** finds a `tailscale serve` run after setup opened, Settings gains a Phone section, and the words
  explain Tailscale plainly. The launch film gets a scene of Odie making an explainer video.
- Smaller: room per reply follows the model (32k where allowed); the video writer gets 64k for its draft and the
  user's sources word for word; copy your own messages; background checks speak only when it matters; Settings lists
  only your own skills; the mic connects faster with a livelier wave.

## v0.1.0 (2026-10)

The first public release.

- Chat from the phone (a PWA over Tailscale): streaming replies, visual blocks, photos, push notifications.
- A brain of your choice: LM Studio or Ollama on the Mac; OpenAI, Claude, Gemini, OpenRouter or any OpenAI-style
  endpoint with a key. A 30-second check tells a model that handles tools from one that doesn't.
- Notes (an Obsidian-style folder) and your Photos library (people, places, dates, what Photos saw) in one index,
  searched together by meaning on the Mac with Odie's own embedding service (EmbeddingGemma 2); each picture one
  vector from its words and its pixels. A video plays after a tap fetches its original from iCloud. Long-term memory
  in one Markdown file.
- Connected apps over MCP (mail, calendar and anything else), on demand, with read-only tools running at once and
  writes asking for a tap.
- Tools: the browser (live frames in the chat), shell commands, files, decks (PDF and PowerPoint), Word documents,
  podcasts with two hosts, markets, reminders, trackers.
- Visual blocks: tables, lists, checklists, charts of eight kinds, heat maps, KPIs, progress, streaks, timelines,
  flash cards, calculators, callouts, photo strips, Mermaid diagrams, SVG drawings and animations, coloured code.
  Every block opens large; the phone pinch-zooms. Pictures, videos and sounds a tool makes show or play inline.
- Long chats keep every word: past the model's limit (up to 300k tokens), turns older than the last five go to the
  model as words only, without their tool traffic and thinking. No summary, no restart, and the prompt cache holds
  between the rare cuts.
- One model layer (ADK's LiteLlm) for every provider; one effort word for thinking; a per-reply line with the tokens
  in and the share from cache.
- Approvals with exact arguments, 24-hour expiry and an audit log. Device pairing with a one-time code.
- Voices: Kokoro locally for read-aloud and podcasts; OpenAI voices, dictation and talk as options.
- The `odie` command: install, status, logs, update with rollback, doctor, uninstall.
