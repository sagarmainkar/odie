---
name: documents
description: Make a designed deck (PDF and PowerPoint, with slide previews) or a Word document the user can download from the chat. Use for "make a deck, slides or a presentation about…", "put this in a Word document", "a report I can share".
metadata:
  title: Decks and documents
  summary: "Designed slide decks (PDF and PowerPoint) and Word documents to download."
  adk_additional_tools: [make_slides, make_document]
---
# Documents

Write the content; Odie does the design. `make_slides` turns it into a designed deck: a PDF and an editable PowerPoint,
with previews of each slide under your reply. `make_document` makes a Word document. Reply in one short line; don't
paste the content into the chat.

Only when the user asks for a deck, slides, a document or a file. An itinerary, a plan or a summary asked for in chat
belongs in chat, drawn with visual blocks; so do follow-ups after a deck ("now an itinerary"), unless they ask for
another file.

For a spreadsheet (.csv), notes (.md), or a calendar event (.ics), use `make_file` instead.

## A deck (`make_slides`)

Each slide starts with `# Title`. Code picks each slide's layout from what you put on it:

| Write on the slide | It becomes |
| --- | --- |
| the first slide: a title, a line under it, maybe `image:` | the cover |
| `- **Lead** — the rest` bullets (up to 6) | points; 2 or 3 read as bold statements |
| bullets and one `image:` | text over a full-bleed photo (`layout: split` puts the photo beside the text) |
| `## Name` cards (2 to 4), each with lines, maybe `image:` and `meta:` | cards (options, people, places, products) |
| `1. Step — detail` (3 to 7) | a row of numbered tiles: a timeline, a plan, a process |
| `stat: value — label` (2 to 4), maybe bullets under | big numbers |
| a ```chart block | a chart: `{"type": "bar" or "line", "x": [...], "series": [{"name": "...", "data": [...]}], "unit": "$"}` |
| `\| a \| b \|` rows | a table |
| only `image:` lines (2 to 4), each maybe with `caption:` | a photo gallery |
| `quote: "..." — who` | a big quote |
| just a title and a line | a section divider |
| a last slide called Thanks or Questions | the closing |

Also on any slide: `kicker: small text above the title`, and `> speaker notes`.

Photos are optional: a research or numbers deck with none is complete. For a trip, a place, a product or a story,
put a photo on most slides: the cover, each place or day (bullets and an `image:` give text over a full photo), cards
with their own photos, and a gallery. Steps, stats and section slides can carry an `image:` too: it becomes their
background, behind a dark veil. Chart and table slides can't. Keep it to 5 to 12 slides, one idea each, few words per bullet.

**Themes** (`theme=`): `minimal` for research, finance and business; `editorial` (the default: dark, great with
photos) for stories, places and guides; `warm` for personal and lifestyle; `bold` for pitches and launches.

A research deck, no photos:

```
# Nvidia, Q2 FY27
kicker: Quarterly review
Data centre still carries the quarter

# The quarter in numbers
stat: $46.7B — Revenue, up 56% y/y
stat: 72.4% — Gross margin

# Revenue by segment
```chart
{"type": "bar", "x": ["Data centre", "Gaming"], "series": [{"name": "Q2", "data": [41.1, 4.3]}], "unit": "$B"}
```

# Bull and bear
## The bull case
Demand broadens beyond the big clouds.
## The bear case
Four customers are half of revenue.
```

A guide, with photos:

```
# Meghalaya
kicker: Trip guide · October
image: https://images.unsplash.com/photo-… (credit: Photo by A Person on Unsplash)
The abode of clouds, in seven days

# Where to stay
## Ri Kynjai
image: https://… (credit: rikynjai.com)
meta: Umiam Lake · Resort
Balconies over the lake; **from ₹14,000**.
## Homestays
meta: Mawlynnong
**₹600–1,000** a night with meals.
```

### Photos

Only use photo addresses a tool gave you, with the credit it gave; never write one yourself. Each `find_images` call
takes a while: get a deck's photos in 2 to 4 broad searches ("Meghalaya landscape", "Shillong"), not one per slide,
and reuse the photos of pages you already opened.
- **A named hotel, restaurant, product or place:** its own page's photos ("Images on this page" when you open its
  listing or site), else a web photo from `find_images` whose title matches.
- **A cover, background or mood:** a free photo from `find_images`.
- **A map or a screen you browsed:** `image: screenshot:<id>`. **The user's own photo:** `image: upload:<id>`.

## A document (`make_document`)

- `#` for the title, `##` for sections, `###` for sub-sections.
- Short paragraphs, with **bold** for the key terms and *italic* for emphasis.
- `- ` and `1. ` lists, `| a | b |` tables, and `---` for a page break.

## Credit

The Word builder comes from Hermes Agent's `docx` skill, by Nous Research (MIT). See `hermes/NOTICE.md`.
