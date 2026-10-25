# Setting up Odie

Everything here is optional except the brain and your name. Setup runs in the browser the first time
(`odie open`); each step there has "do it in Settings instead", and all of it can be changed later in Settings.

## 1. The brain

Odie talks to any model through an OpenAI-style API. Pick one:

| Choice | How | Leaves the computer? |
|---|---|---|
| **LM Studio** (local) | Install LM Studio, download a chat model that supports tool calls (Gemma 4 12B or 26B QAT are good on 32 GB; Qwen 3.6 35B-A3B works), start its server (default `http://localhost:1234`). Odie lists what's loaded. | No |
| **Ollama** (local) | `brew install ollama`, `ollama pull gemma4:12b` (or another chat model). Odie lists what's pulled. | No |
| **Ollama cloud models** | Sign in to Ollama; models like `deepseek-v4.1-flash:cloud` appear in the same list. | Yes, to Ollama |
| **OpenAI / Claude / Gemini / OpenRouter** | Paste a key in Settings → Providers (it goes to `~/.odie/.env`). | Yes |
| **Any OpenAI-style endpoint** | Settings → Providers → Custom: a base URL and a key. | Depends |

Setup checks the model you pick in about 30 seconds: that it uses tools correctly, that it reads a tool's result,
its speed and its context size. A model that mangles tool calls is told apart from one that's just slow.

A small local model works for chat; drawing rich visuals and using the browser well wants a bigger one or a cloud
one. Settings → Brain marks the choices that leave the computer.

## 2. Your name, Odie's name, its personality

Setup asks your name and what to call the assistant. Its personality is `~/.odie/SOUL.md`, plain text you can
edit in Settings → Personality.

## 3. Notes (your vault)

Settings → Notes: a folder of Markdown files (an Obsidian vault works as is). Odie searches it by keyword, and by
meaning when you choose an embedder. It reads the vault and never changes it. Long-term memory is one Markdown file,
`~/.odie/memories.md` (`ODIE_MEMORY_FILE` moves it, into the vault for example), so you can read and edit what it
remembers.

**Search by meaning, on the Mac.** Setup's "Search by meaning" step offers, in this order: the embedding models
already running in LM Studio or Ollama on this computer, then **a server somewhere else** (Ollama at its root address,
such as `http://studio.local:11434`, or LM Studio, llama.cpp and any OpenAI-style server at its `/v1` address: type the
address, press Find models, pick one), then OpenAI. **EmbeddingGemma 2 on Ollama** (`ollama pull embeddinggemma-2`,
about 1.3 GB, loaded when asked and unloaded by Ollama when idle) reads notes and pictures alike, nothing leaves the
computer, and it is recommended when found; the rest are text only. Settings → Notes → Change offers the same choices
later. Odie's own embedding service (`embed_server/`, EmbeddingGemma 2 in PyTorch) is no longer built by default:
install with `ODIE_EMBED=on` to have it, and it then appears as the last choice (it downloads the 1.5 GB model from
Hugging Face into `~/.cache/huggingface` on first use, runs on `ODIE_EMBED_PORT`, and unloads the model after
`ODIE_EMBED_IDLE_MINUTES` idle).
The first pass over a few thousand notes takes about a quarter of an hour; Settings → Notes counts it up.

## 3b. Photos and videos

Setup asks once whether Odie may look at your Photos library (Settings → Photos later: Turn on, Off, Screenshots too).
With a yes, Odie reads what Photos already knows about each picture and video, read-only: the people in it, what it
shows, where and when it was taken, its albums, and Apple's extras (holidays, pets, landmarks, text seen in the
picture). Nothing leaves the Mac and nothing is changed; hidden items and the bin are never read. The library is read
in seconds, again every half hour, into the same index as the notes.

With Odie's own embedding service, or EmbeddingGemma 2 on Ollama, each picture also gets one vector from its words and
its pixels together (a video from its poster frame), about 35 minutes for eight thousand pictures, after the notes. One search then runs over notes
and pictures alike: "pictures of Asha in Goa last May" lists a few with thumbnails and says how many more match. With a
text-only embedder, pictures are found by their words alone, and the Photos row says so.

A video plays after a tap: its original is usually in iCloud, so Play asks Photos to download it (a few seconds to a
minute) into `~/.odie/data/photos-fetched`, then it plays, on the phone too. The files stay until you empty the folder.
macOS may ask once, on the Mac, to let Odie's Python use Photos; if it refuses, the Photos row says what to allow under
Privacy & Security.

## 3c. Where you are

The chat asks once, under the composer, whether Odie may know where you are; Allow lets the browser ask its own question
once, and every later open refreshes the place quietly. The server keeps the latest place name and the last 30 days of
points, works out home as the place seen most on nights, and puts only the place name and home into the context line
your chat model gets with each message, never coordinates. Turning a point into a name may ask OpenStreetMap when no
recent point nearby is known. Settings → Location shows the place, when it was seen and home, with Off and Forget.

## 4. Web search

Searching the web uses whichever key you add in Settings → Web search: [Tavily](https://tavily.com) (a free tier is
enough), Brave or Ollama, tried in that order. Without a key Odie uses a free fallback (DuckDuckGo, pages read
directly), and it still opens pages you name with its own browser.

## 5. Connected apps (MCP)

Any MCP server becomes an app. `~/.odie/mcp.json` uses the standard `mcpServers` shape:

```json
{
  "mcpServers": {
    "mail": {
      "command": "/opt/homebrew/bin/node",
      "args": ["/path/to/your-gmail-server/dist/index.js"],
      "env": { "GMAIL_ACCOUNT": "personal" },
      "title": "Mail and Calendar",
      "description": "My Gmail and Google Calendar: search and read mail, drafts, labels; events, free time"
    },
    "notes-service": {
      "url": "http://127.0.0.1:8766/mcp",
      "headers": { "X-Profile": "me" },
      "title": "Notes service",
      "description": "Another MCP server over HTTP"
    }
  }
}
```

Each app is on demand: its tools switch on when the model loads the app's skill, so the system prompt stays
small. Every tool asks for a tap until you turn on "Reading doesn't need a tap" for the app; then tools whose names
say they read (find, get, list, search, fetch) run at once, and the rest (send, create, delete) still ask. An app whose
tools look like a mail listing or a calendar is also used by the watcher: trackers like "tell me when she replies"
and the morning look at what's due. Settings → Apps shows each server's status and tools.

## 6. The phone

Odie listens on `127.0.0.1:8000` only. The phone reaches it over your Tailscale network:

1. Tailscale on the Mac and on the phone, same account.
2. On the Mac, once: `scripts/serve-tailscale.sh` (it runs `tailscale serve` and prints the HTTPS address).
3. On the phone, open that address, Share → Add to Home Screen, open it from the icon (push notifications on iOS
   only work from a Home Screen app).
4. Type the pairing code from `odie pair` (valid once, ten minutes). A recovery passcode is shown once in Settings.

Browsers that haven't paired see nothing but the pairing screen. `odie pair` again adds another device.

## 7. Voices

- **Read-aloud and podcasts** use Kokoro on the Mac by default (Odie's own voice worker, started with the service;
  `ODIE_VOICE=off` turns it off). OpenAI voices are an option with an OpenAI key.
- **Dictation**: with an OpenAI key the words appear as you speak; without, the phone's own keyboard mic works.
- **Talk** (a spoken conversation) needs an OpenAI key.

## The odie command

Odie runs as a background service (launchd starts it at login and restarts it if it stops). `odie` manages it:

```
odie start        start Odie in the background (and at every login from now on)
odie stop         stop it (it stays stopped until `odie start`, even after a reboot)
odie restart      stop + start
odie status       running or not, version, address, health, which model
odie pair         a one-time pairing code (valid once, 10 minutes) for a device other than this Mac's browser
odie logs         follow the server log (-e for errors only, -n 200 for the last 200 lines)
odie open         open Odie in the browser
odie update       move to the newest release: fetch, install, build, restart, health check
odie update --rollback   go back to the version before the last update
odie doctor       check everything Odie needs and say how to fix what's wrong (it changes nothing)
odie uninstall    remove the service, the command and the app copy; asks separately before deleting your data
```

Updates follow releases (tags like `v0.2.0`); `ODIE_BRANCH=main scripts/install.sh` makes an install follow `main`
instead, for working on Odie itself. An update never leaves you without a working Odie: if the build fails, or the restarted service isn't healthy within
a minute, it goes back to the previous version by itself. The build's output is in `~/.odie/logs/update.log`.

## Where things live

```
~/.odie/                owner-only
├── .env                keys and settings (NAME=value)
├── SOUL.md             personality
├── mcp.json            connected apps
├── memories.md         long-term memory (or in your vault)
├── skills/             skills you add
├── data/               chats, settings, approvals, audit, the index (odie-index.db: notes and photos), push keys, uploads,
│                       photos-fetched/ (originals fetched from iCloud), workspace/ (files tools make)
├── logs/               server, update and install logs
└── app/                Odie's own copy of the code (odie update replaces it)
```

Back up `~/.odie` (without `app/` and `logs/`). Delete it to start over. Move it with `ODIE_HOME`.

## Settings in `~/.odie/.env`

Besides the keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `TAVILY_API_KEY`):

| Name | What it changes | Default |
|---|---|---|
| `ODIE_MODEL` | The model used when none is chosen in Settings, if a local provider lists it | |
| `LM_STUDIO_BASE_URL` | LM Studio's address | `http://localhost:1234/v1` |
| `OLLAMA_BASE_URL` | Ollama's address (another computer works) | `http://localhost:11434/v1` |
| `OPENAI_BASE_URL`, `OPENROUTER_BASE_URL`, `GEMINI_BASE_URL`, `ANTHROPIC_BASE_URL` | A provider's address | the provider's own |
| `ODIE_TIMEZONE`, `ODIE_LOCALE`, `ODIE_CURRENCY` | The clock, number and money formats in the prompt | from the Mac |
| `ODIE_VOICE` | `off`: no local voice worker | on |
| `ODIE_TTS_MODEL`, `ODIE_STT_MODEL` | OpenAI's read-aloud and transcription models, for when OpenAI retires one | `gpt-4o-mini-tts`, `gpt-4o-mini-transcribe` |
| `ODIE_VIDEO_VOICE` | The voice explainer videos are narrated in (a voice's id or name, any engine), kept when the read-aloud voice changes | the read-aloud voice |
| `ODIE_PORT` | The port the service listens on | 8000 |
| `ODIE_EMBED` | `on`: build and run Odie's own embedding service (EmbeddingGemma 2 in PyTorch); Ollama's `embeddinggemma-2` is the default way | off |
| `ODIE_EMBED_PORT` | The embedding service's port | Odie's port + 772 |
| `ODIE_EMBED_IDLE_MINUTES` | Minutes without a request before the embedding model is unloaded (0: never) | 15 |
| `HF_TOKEN` | A Hugging Face token, passed to the embedding service (not needed: the model is public) | |

## If something's wrong

`odie doctor` checks the service, the brain, search, the notes index, voices and Tailscale, and says what to fix.
`odie logs -e` shows errors. `odie update --rollback` goes back to the version before the last update.
