# Changelog

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
