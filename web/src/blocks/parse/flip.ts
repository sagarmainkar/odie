import { clean, firstText, https, keepFirst, str, type Trail } from "./fields";

export type FlipCard = { front: string; back: string; image?: string };
export type FlipBlock = { type: "flip"; title?: string; cards: FlipCard[] };

/**
 * flip: flash cards, each with a front (the question) and a back (the answer, with a photo when the model gives one).
 * "question" and "answer" are taken as the front and back too, since models guess those names.
 *   {type: "flip", cards: [{front: "Most golds?", back: "China · 201"}, {question: "Host?", answer: "Nagoya"}]}
 *   → {type: "flip", cards: [{front: "Most golds?", back: "China · 201"}, {front: "Host?", back: "Nagoya"}]}
 * Dropped: a card without a front or a back; the whole block when no card is left; cards past the 12th.
 */
export function readFlip(raw: any, here: Trail): FlipBlock | null {
  const rawCards = Array.isArray(raw.cards) ? raw.cards : [];
  const cards: FlipCard[] = [];
  rawCards.forEach((c: any, i: number) => {
    const front = firstText([c?.front, c?.question], 80);
    const back = firstText([c?.back, c?.answer], 120);
    if (!front || !back) {
      here.at("cards").at(i).drop("card needs a front and a back");
      return;
    }
    cards.push(clean({ front, back, image: https(c.image) }));
  });
  if (cards.length === 0) return here.drop("flip has no cards");
  return clean({ type: "flip" as const, title: str(raw.title, 60), cards: keepFirst(cards, 12, here, "cards") });
}
