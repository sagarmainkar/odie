import { clean, firstList, firstText, firstTextOrNumber, https, icon, keepFirst, type Trail } from "./fields";
import type { IconName } from "../../components/Tile";

export type ListItem = { title: string; subtitle?: string; value?: string; icon?: IconName; image?: string; run?: string; url?: string };
export type ListBlock = { type: "list"; title?: string; ranked: boolean; items: ListItem[] };

const MAX_ITEMS = 12;

/**
 * list: rich rows for rankings, search results, places or a short set of picks.
 * - items (also `rows`), up to 12: {title (also `name`/`label`, else `text`), subtitle (also `description`/`detail`/
 *   `note`/`text`), value: the right-hand text (also `price`/`rating`/`score`/`meta`/`badge`; numbers become text),
 *   icon or image (https), run (tap sends a message, also `ask`) or url (https, opens)}. A plain string is a title-only
 *   row.
 * - ranked: true numbers the rows (also `numbered`). title: optional heading over the list.
 *   {type: "list", numbered: true, items: ["Third Wave", {name: "Dyu Art Café", description: "Garden seats", rating: 4.6}]}
 *   → {type: "list", ranked: true, items: [{title: "Third Wave"}, {title: "Dyu Art Café", subtitle: "Garden seats", value: "4.6"}]}
 * Dropped: no item with a title.
 */
export function readList(raw: any, here: Trail): ListBlock | null {
  const list = firstList([raw.items, raw.rows]);
  if (!list) return here.drop("list needs items");
  const items: ListItem[] = [];
  list.forEach((item, i) => {
    const row = readListItem(item);
    if (!row) {
      here.at("items").at(i).drop("row has no title");
      return;
    }
    items.push(row);
  });
  if (!items.length) return here.drop("list has no row with a title");
  const ranked = raw.ranked === true || raw.numbered === true;
  const title = firstText([raw.title], 60);
  return clean({ type: "list" as const, title, ranked, items: keepFirst(items, MAX_ITEMS, here, "rows") });
}

/**
 * A ranked list under a name models guess when they draw from memory ("ranked", "ranked list", "ranking"): read as a
 * list with numbered rows. A row's `rank` is ignored, since the order is the rank.
 *   {type: "ranked", items: [{rank: 1, name: "Vidyarthi Bhavan", detail: "MG Road"}]}
 *   → {type: "list", ranked: true, items: [{title: "Vidyarthi Bhavan", subtitle: "MG Road"}]}
 */
export function readRankedList(raw: any, here: Trail): ListBlock | null {
  return readList({ ...raw, ranked: true }, here);
}

/**
 * One row, or null when it has no title. With no title, name or label, the row's `text` is its title (up to 160
 * characters: it is all the row says); otherwise `text` is the line under it. The value may come as `score` or `badge`.
 *   {text: "**MTR**, the gold standard", score: 5}  → {title: "**MTR**, the gold standard", value: "5"}
 *   {name: "CTR", text: "Benne dosa", badge: "Iconic"} → {title: "CTR", subtitle: "Benne dosa", value: "Iconic"}
 */
function readListItem(item: any): ListItem | null {
  if (typeof item === "string") {
    const title = firstText([item], 80);
    return title ? { title } : null;
  }
  if (!item || typeof item !== "object") return null;
  const named = firstText([item.title, item.name, item.label], 80);
  const title = named ?? firstText([item.text], 160);
  if (!title) return null;
  const textUnder = named ? item.text : undefined;  // a text already used as the title isn't repeated under it
  const value = firstTextOrNumber([item.value, item.price, item.rating, item.score, item.meta, item.badge], 30);
  return clean({
    title,
    subtitle: firstText([item.subtitle, item.description, item.detail, item.note, textUnder], 160),
    value,
    icon: icon(item.icon),
    image: https(item.image),
    run: firstText([item.run, item.ask], 300),
    url: https(item.url),
  });
}
