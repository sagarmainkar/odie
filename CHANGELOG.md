# Changelog

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
