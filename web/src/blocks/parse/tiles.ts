import { clean, firstList, https, icon, keepFirst, str, textOrNumber, type Trail } from "./fields";
import type { IconName } from "../../components/Tile";

export type TileItem = { title: string; subtitle?: string; image?: string; icon?: IconName; run?: string; ask?: string };
export type TilesBlock = { type: "tiles"; items: TileItem[] };

const SUBTITLE_MAX = 80;

/**
 * tiles: cover cards, up to 8 (items, also `tiles`). Each needs a title; the image must be https and the icon one of the
 * app's names (otherwise that field is left off, the tile stays).
 *   {type: "tiles", items: [{title: "Kyoto", image: "javascript:x", icon: "nope", run: "Plan Kyoto"}, {subtitle: "no title"}]}
 *   → {type: "tiles", items: [{title: "Kyoto", run: "Plan Kyoto"}]}
 * Dropped: no item with a title.
 */
export function readTiles(raw: any, here: Trail): TilesBlock | null {
  const list = firstList([raw.items, raw.tiles]);
  if (!list) return here.drop("tiles needs items");
  const items: TileItem[] = [];
  list.forEach((item: any, i: number) => {
    const tile = readTile(item);
    if (!tile) {
      here.at("items").at(i).drop("tile has no title");
      return;
    }
    items.push(tile);
  });
  if (!items.length) return here.drop("tiles has no item with a title");
  return { type: "tiles", items: keepFirst(items, 8, here, "tiles") };
}

// The fields a tile's title may come in, best first. Models writing from memory give tiles a `label` (or only a
// `text` or `caption`) instead of a title.
const TITLE_FIELDS = ["title", "label", "name", "caption", "text"];
// The fields that say more about the tile, in the order they're shown under the title.
const MORE_FIELDS = ["subtitle", "value", "text", "caption", "note", "description"];

/**
 * One tile, or null when no field can be its title. The first of TITLE_FIELDS is the title; the rest of the tile's
 * text (MORE_FIELDS, minus the one used as the title) goes under it, joined with " · ".
 *   {label: "Right now", value: "24°C · overcast", note: "0 mm rain"} → {title: "Right now", subtitle: "24°C · overcast · 0 mm rain"}
 *   {label: "Seat & meal", text: "Window seat · Veg meals"}         → {title: "Seat & meal", subtitle: "Window seat · Veg meals"}
 *   {subtitle: "no title"}                                           → null
 */
function readTile(item: any): TileItem | null {
  if (!item || typeof item !== "object") return null;
  const titleField = TITLE_FIELDS.find((f) => str(item[f]) !== undefined);
  if (!titleField) return null;
  const more: string[] = [];
  for (const f of MORE_FIELDS) {
    const text = textOrNumber(item[f], SUBTITLE_MAX);
    if (f !== titleField && text !== undefined) more.push(text);
  }
  const subtitle = more.length ? more.join(" · ").slice(0, SUBTITLE_MAX) : undefined;
  return clean({
    title: str(item[titleField], 40)!, subtitle, image: https(item.image), icon: icon(item.icon),
    run: str(item.run, 300), ask: str(item.ask, 300),
  });
}
