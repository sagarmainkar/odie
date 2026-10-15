"""A one-line reminder to draw, on messages that look like they read better drawn (2026-10-12).

Why: the visual blocks catalogue sits in the system prompt (odie.blocks.visuals_prompt), thousands of tokens before the
question. Local Gemma, with that long a prompt, answered a three-phone comparison with a Markdown table and wrote a
packing list in a fence and a tag of its own (chat of 12 Oct). A short line right after the question points it back.

How: the runner adds NUDGE at the very end of the user's message, after the "[context: …]" note, on turns where
looks_visual says yes. It's saved with the message and goes to the model as sent in later turns, like the note, so
every request still starts with the one before. The chat's history hides it with the note (runner.strip_trailer).
"""
from __future__ import annotations

import re

NUDGE = "[If this reads better drawn, draw it with the Visual blocks: an ```odie-blocks fence, as in your instructions.]"

# Questions that read better drawn, in the words people ask them: comparisons, top-N and best-X picks, plans and
# itineraries, packing and to-do lists, steps and how-tos (renewing or applying for something), loan and money
# what-ifs, safety questions, prices, weather, histories or trends over time, flash cards and quizzes, and grids of
# numbers (a heat map, something by quarter or month).
_VISUAL_ASK = re.compile(
    r"\b(compare|comparing|comparison|vs|versus|top \d+|top (three|five|ten)|best|itinerary|plan|planning|"
    r"packing|pack|checklist|to-?do list|list of|steps|step by step|how do i|how to|renew\w*|apply|"
    r"emi|loans?|sip|budget|split|how much|what if|prepay\w*|pay (it )?off|is it safe|safe to|prices|"
    r"weather|forecast|rain|timeline|history of|trend|flash ?cards?|quiz|heat ?map|by (quarter|month|weekday))\b",
    re.IGNORECASE,
)
# Asking for a file (a deck, a document, a PDF) or a podcast: their own skills make those, not blocks.
_FILE_ASK = re.compile(r"\b(pdf|decks?|slides?|docx?|documents?|pptx|presentation|podcast)\b", re.IGNORECASE)
# A whole message that only closes the topic: thanks, no, bye. After one of these there's nothing to draw.
_CLOSER = re.compile(r"^\s*(thanks|thank you|thx|ty|no|nope|nah|bye|good night|cool|great|nice|perfect|awesome|ok thanks)\W*$",
                     re.IGNORECASE)
_WORD = re.compile(r"\w+")
SHORT = 3  # words at most in a follow-up: "yes", "ok", "go ahead", "and day 2"


def looks_visual(text: str, previous_reply: str = "") -> bool:
    """Decides whether this message gets the nudge to draw: yes when it asks for something that reads better drawn
    (and isn't asking for a file), or when it's a short follow-up to a reply that drew blocks. Worked examples:
      "Compare Pixel 10a, Galaxy A76 and Nothing Phone 4 …"       -> True  (compare)
      "Packing list for 3 days in Ooty in December"               -> True  (packing)
      "Home loan of 40 lakh at 8.5%. What's my EMI?"              -> True  (loan, EMI)
      "How do I renew my passport?"                               -> True  (how do I, renew)
      "Flash cards, let's play"                                   -> True  (flash cards)
      "Which finance stocks are up, by quarter?"                 -> True  (by quarter: a heat map)
      "yes", after a reply with an ```odie-blocks fence           -> True  (a short follow-up to blocks)
      "yes", after a plain-text reply                             -> False
      "Make me a one-page PDF of the Mysore plan"                 -> False (a file: the documents skill)
      "What's the capital of France?"                             -> False"""
    if _FILE_ASK.search(text):
        return False
    if _VISUAL_ASK.search(text):
        return True
    return is_short_follow_up_to_blocks(text, previous_reply)


def is_short_follow_up_to_blocks(text: str, previous_reply: str) -> bool:
    """Decides whether this is a short reply (SHORT words at most) to an answer that drew blocks, photos or a chart,
    and not one that closes the topic. Worked examples:
      "ok" after "```odie-blocks …"           -> True
      "go ahead" after the same               -> True
      "thanks!" after the same                -> False (closes the topic)
      "What can you do here?" after the same  -> False (four words: a new question)
      "yes" after "Sure, which city?"         -> False (nothing was drawn)"""
    if "```odie-" not in previous_reply:
        return False
    if _CLOSER.match(text):
        return False
    return is_short(text)


def is_short(text: str) -> bool:
    """Decides whether a message is short enough to be a follow-up: 1 to SHORT words. "go ahead" -> True; "" -> False;
    "what about the weekend" -> False."""
    return 0 < len(_WORD.findall(text)) <= SHORT
