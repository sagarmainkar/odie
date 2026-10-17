---
name: documents
description: Make a designed deck (PDF and PowerPoint, with slide previews) or a Word document the user can download from the chat. Use for "make a deck, slides or a presentation about…", "put this in a Word document", "a report I can share".
metadata:
  title: Decks and documents
  summary: "Designed slide decks (PDF and PowerPoint) and Word documents to download."
  adk_additional_tools: [make_deck, make_document]
---
# Documents

Decks: you brief the deck; a separate writer writes the slides. `make_deck` returns at once; in the background the
writer turns your brief into slides, Odie designs and builds them (a PDF and an editable PowerPoint, with previews of
each slide), and the deck is posted to this chat with a ping on the phone. You never write the slides yourself.
Word documents: `make_document` turns your Markdown into one, under your reply.

Only when the user asks for a deck, slides, a document or a file. An itinerary, a plan or a summary asked for in chat
belongs in chat, drawn with visual blocks; so do follow-ups after a deck ("now an itinerary"), unless they ask for
another file.

For a spreadsheet (.csv), notes (.md), or a calendar event (.ics), use `make_file` instead.

## A deck (`make_deck`)

Do the research first (the web, the user's notes, the pages you browse); the writer can't.

### Write the brief

The writer can't see this chat, the user's notes, memory or the web, and can't search for photos: it knows only the
topic, the theme and the brief. So the brief carries everything else:

- **the angle:** who it's for and what the deck is about;
- **the slides' points, in order** (the user's number of slides, if they gave one; else 5 to 12);
- **the facts it must use:** names, numbers, prices and details from this chat, the notes or your searches;
- **the photo addresses, each with its credit,** exactly as `find_images` or the browser returned them, and which
  slide or card each is for. Only these can go on the slides.

Photos are optional: a research or numbers deck with none is complete. For a trip, a place, a product or a story,
put a photo on most slides: find them first and put them in the brief (the cover, each place or day, each card).
Each `find_images` call takes a while: get a deck's photos in 2 to 4 broad searches ("Meghalaya landscape",
"Shillong"), not one per slide, and reuse the photos of pages you already opened.
- **A named hotel, restaurant, product or place:** its own page's photos ("Images on this page" when you open its
  listing or site), else a web photo from `find_images` whose title matches.
- **A cover, background or mood:** a free photo from `find_images`.
- **A map or a screen you browsed:** `screenshot:<id>`. **The user's own photo:** `upload:<id>`.

Only what the deck needs: plain text, up to 6,000 characters.

### The call

```
make_deck(
  topic="A weekend in Coorg",
  theme="editorial",
  brief="For a family of four from Bengaluru, by car. 1. Cover. 2. The drive: 5 hours, leave by 6. 3. Where to stay:
Tamara Coorg (from ₹28,000), a homestay in Madikeri (₹3,000). 4. Two days, hour by hour. 5. Food to try. Photos:
cover https://images.unsplash.com/photo-… (credit: Photo by A Person on Unsplash); Tamara https://… (credit:
thetamara.com).",
)
```

- `topic`: a few words.
- `theme`: `minimal` for research, finance and business; `editorial` (the default: dark, great with photos) for
  stories, places and guides; `warm` for personal and lifestyle; `bold` for pitches and launches.
- **A change to a deck made earlier** ("make slide 2 shorter", "add a budget slide"): `revise="<its name>"`, the
  deck's name as this chat saw it in "The deck about … is ready." (or the name the user uses), and the brief says
  what to change, with any new facts and photos. The newest version of that deck is the one changed, so a second
  change builds on the first. Pass the theme it had unless the user asks for another.

### The reply

On `{"result": …}`, reply in one or two lines, with no emojis: it's being made, about how long (the range the result
gives), it will appear in this chat with a ping on the phone, and they can keep chatting meanwhile. Never repeat the
brief. On `{"error": …}`: fix exactly that and call again.

## A document (`make_document`)

- `#` for the title, `##` for sections, `###` for sub-sections.
- Short paragraphs, with **bold** for the key terms and *italic* for emphasis.
- `- ` and `1. ` lists, `| a | b |` tables, and `---` for a page break.

## Credit

The Word builder comes from Hermes Agent's `docx` skill, by Nous Research (MIT). See `hermes/NOTICE.md`.
