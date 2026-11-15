# Bots in Odie: the UX

Mockup: `mockup.html` in this folder (frames A to I are named below). Nothing in the repo was changed.

## The idea

A bot is someone you chat with, like a WhatsApp contact. The list looks like OpenBot's, in colour. Tapping a bot opens
Odie's chat screen, owned by that bot. Odie is the pinned first row; the chief is second. One left drawer switches bot
and conversation.

## 1. Where things live

- **Phone.** Today stays home. Today gets one Bots card (frame H); "All bots" opens the **Bots list** (frame A,
  `#bots`). The chat's back route is the drawer, whose top icon goes to Today.
- **Desktop.** The rail keeps its five tabs. Chat gains a **column of bot avatars** next to the rail, then that bot's
  conversations, then the chat (frame I). There is no separate Bots list screen on a desktop: the column is the list.
- **Odie** is a row like the others but pinned first, in its own card, with its own round face. Only Odie has memory,
  mail, calendar, reminders and the morning brief; its row says so. Today's ask bar still opens Odie.
- **The chief** is pinned second, always the violet hexagon. Its row shows "Team at work · 3 of 4 done" while it runs.
  Teammates are ordinary bots in the same list.

Trade-off: a bottom tab bar would make Bots one tap closer, but Odie has no tab bar on the phone and Today is the home
he opens. One card on Today costs less than a new navigation model.

## 2. The Bots list (frames A, F, G)

**Row:** avatar (52 px) · name and time · grey one-line role · one-line preview.

- Preview: the last message. While the bot works, it becomes a live line with a pulsing dot ("Team at work · 3 of 4
  done", "reading zigwheels.com…") and the avatar gets a turning dashed ring and looking-around eyes.
- Time: last activity. A small repeat mark means the bot runs on a schedule.
- **Needs you:** an amber "Needs your tap" chip replaces the time, the avatar gets an amber halo, and the preview is
  the question. **Unread:** a brand-colour dot and a bold preview. Dots only, no counts.
- **Order:** Odie, chief, then bots that need you, then by latest activity. He can pin a bot.
- **Search** sits at the bottom, in thumb reach, and searches bot names and conversation text.
- **Adding a bot:** the + opens one sheet with one field: "What should it do?" The chief drafts name, role,
  instructions and powers; he reviews them in the details sheet and saves. "Start blank" is a link there. Asking the
  chief in chat ("make me a bot that…") lands in the same review.
- **Long-press a row:** Pin, Mute its pushes, Details, Delete (not for Odie or the chief).

### The creatures

Each bot's look is three picks from a hash of its name, **stored when the bot is made** so it never changes:

- **Shape** (8): hexagon, cloud, squircle, pentagon, pill, gumdrop, triangle, flower. The circle is Odie's alone.
- **Colour** (8): coral, amber, teal, sky, violet, lime, pink, slate, taken from the existing cast palette. A new bot
  takes the next free colour if its hash lands on one already used, so a small team never has two alike.
- **Eyes** (6): round, tall, calm (closed arcs), stern, wide dots, side-eye with a brow.

Each is one inline SVG: a soft radial gradient, a shared noise filter that roughens the outline into fur, dark eyes
with a glint, a shadow in its own colour. The same colours work by day and night (frame F). Bots have eyes only; Odie
keeps its mouth. "Shuffle look" in the details re-rolls.

## 3. Talking to a bot (frames B, C)

- **Tap a bot → its latest conversation**, ready to type, like WhatsApp. The compose button (top right) starts a new
  conversation. Other conversations are in the drawer.
- **Header:** drawer button · avatar, name and a small line (model and powers; for the chief, who it leads) · compose.
  Tapping the name opens details.
- **A direct conversation is a real chat.** Each message is answered by that bot, with its prompt, model, powers and
  `notes.md`, and with this conversation's history. Replies stream like Odie's. Above a reply a small grey line says
  what it did ("Read 3 sites · 14 s"); it opens to the steps.
- **Long work does not block.** If he leaves, the turn carries on as the job it already is; the list shows the live
  line and a push arrives when it ends. This keeps the one-shot background job as the engine and puts a chat on top.
- **The chief (frame C).** Its turn shows the team card in place of the steps line: the chief, then each teammate
  with avatar, model, time, steps and current step. When the answer arrives the card folds to one pill ("3 bots ·
  5m 02s · 83 steps") that reopens it; a teammate's row opens its full report.
- **`@chief …` in Odie's chat stays.** Odie shows the same team card and the answer. That run also appears in the
  bot's conversation list, marked "asked by Odie from your chat", so nothing a bot did is hidden from its own history.
- **Scheduled runs** ("every weekday 8:30") live in one conversation of their own under "Runs by itself", so the
  morning notes pile up in one place.

Trade-off: a bot needs a per-conversation history, which the one-shot job lacks today. Without it the list would be
a list of job reports.

## 4. Switching bots

- **Phone: one left drawer (frame D).** The top-left button or a swipe from the left edge opens it. Its left edge is
  a strip of avatars (Today, Odie, chief, the bots, +, all bots); the rest is the chosen bot's conversations with New
  conversation, Notes and Search. Tapping an avatar swaps the list in place; tapping a conversation opens it. Dots on
  the strip show working, needs you and unread.
  Why: it is where Odie's threads drawer already is, and it answers "which bot" and "which conversation" on one
  surface (Discord's pattern). A header dropdown hides the bots; a strip above the chat costs height on every screen.
- **Desktop: the same drawer, pinned open** as two columns beside the rail (frame I): avatars, then conversations.
  Slack's layout, the phone's components.

## 5. Details and taps (frames E, B, H)

- **Details sheet** from the header name or the drawer's gear: the creature (Shuffle look), name, role; Model (any
  provider's, or "the chat's"); Instructions; Runs by itself; Powers as four switches (Web, Files, Signed-in browser,
  Shell); Memory notes (a preview of `notes.md`, Open to read and edit); Delete. A line says who made it ("Made by
  Chief · edited by you"). Settings → Bots becomes a link to the Bots list.
- **A tap is asked in three places, answered once:** a card in the bot's own conversation (Allow / Deny, with the
  9-minute rule in words), the same card on Today, and the amber chip on its row and strip avatar. Only the app's
  buttons answer, as now. Sign-in asks use the same card with Sign in / Done / Skip.

## 6. First run, empty states, Today

- **First run (frame G):** Odie, then "Starter team": chief, researcher, checker, contrarian, each with a one-line
  hello as its preview, then a dashed card "Make a bot of your own" with three example chips.
- **An empty conversation:** the creature large, its role, its powers, three starter questions.
- **Today (frame H):** one Bots card: a row of avatars (working and needs-you first), then a line for each open
  question with Allow / Deny, and a line per bot at work. Finished reports show as the unread dot, not rows. Bot jobs
  leave the Jobs section, so nothing shows twice.

## Screens

| Screen | New or changed | Frame |
|---|---|---|
| Bots list | new (phone and tablet) | A, F, G |
| Chat, owned by a bot | changed: header, drawer button, compose | B, C |
| Drawer / desktop columns | changed: avatar strip added to Threads | D, I |
| Bot details sheet | new (replaces Settings → Bots) | E |
| New bot sheet | new | (not drawn) |
| Today's Bots card | new | H |

## Tap paths

- Ask a bot: Today → Bots card → bot → type.
- Switch bot mid-chat: swipe from left → avatar → conversation (or New conversation).
- Answer a tap: push → the bot's conversation → Allow. Or Today → Allow.
- Change a model: header name → Model.
- Make a bot: Bots → + → one sentence → review → Save.

## What I would not build

- Group chats with several bots, or bots talking to each other in view. The chief and its team card are that.
- Sharing, a bot store, import/export, anything multi-user.
- An avatar editor, photo avatars, per-bot wallpapers or themes.
- Folders or tags for bots; pinning and search are enough for a dozen.
- Unread counts; a dot is enough for one person.
- Talk mode and a voice per bot (Odie keeps the voice).
- Bots reading Odie's memory, mail or calendar on their own. Odie hands them a brief.
- A bottom tab bar on the phone.
