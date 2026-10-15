# Changelog

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
