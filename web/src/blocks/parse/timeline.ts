import { clean, firstList, firstText, icon, keepFirst, str, type Trail } from "./fields";
import type { IconName } from "../../components/Tile";

export type Stop = { time?: string; title: string; place?: string; note?: string; icon?: IconName };
export type TimelineBlock = { type: "timeline"; title?: string; groups: { label: string; items: Stop[] }[] };

const TIME_MAX = 12;  // characters the time column has room for ("09:00", "Sat 10:30")

/**
 * timeline: a plan in groups (days), up to 14 groups of 12 stops. A stop needs a title; a group with no stops left
 * is dropped. Models drawing from memory write one flat list of stops (`events`, `items`, `steps` or `stops`) instead
 * of groups: that is one group with no label, under the timeline's title.
 *   {type: "timeline", groups: [{label: "Day 1", items: [{time: "09:00", title: "Fushimi Inari"}, {note: "no title"}]}, {label: "empty", items: []}]}
 *   → {type: "timeline", groups: [{label: "Day 1", items: [{time: "09:00", title: "Fushimi Inari"}]}]}
 *   {type: "timeline", title: "Day 1", events: [{time: "09:00", title: "Check in", text: "Let parents settle"}]}
 *   → {type: "timeline", title: "Day 1", groups: [{label: "", items: [{time: "09:00", title: "Check in", note: "Let parents settle"}]}]}
 * Dropped: no groups and no flat list, or no group with a stop.
 */
export function readTimeline(raw: any, here: Trail): TimelineBlock | null {
  const found = groupsOf(raw, here);
  if (!found) return here.drop("timeline needs groups");
  const groups: { label: string; items: Stop[] }[] = [];
  found.forEach(({ group: g, at }) => {
    const list = firstList([g?.items, g?.events, g?.stops, g?.steps]);
    if (!list) {
      at.drop("group has no items list");
      return;
    }
    const stops: Stop[] = [];
    list.forEach((it: any, i: number) => {
      const stop = readStop(it);
      if (!stop) {
        at.at("items").at(i).drop("stop has no title");
        return;
      }
      stops.push(stop);
    });
    if (!stops.length) {
      at.drop("group has no stop with a title");
      return;
    }
    groups.push({ label: str(g.label, 50) ?? "", items: keepFirst(stops, 12, at, "stops") });
  });
  if (!groups.length) return here.drop("timeline has no group with a stop");
  return clean({ type: "timeline" as const, title: str(raw.title, 60), groups: keepFirst(groups, 14, here, "groups") });
}

/**
 * Where the timeline's groups are, each with its place in the fence (for the notes). A flat list of stops is one group
 * with no label: the timeline's title already says what it is, so it isn't drawn twice.
 *   {groups: [{label: "Day 1", items: […]}]}            → that group, at "groups.0"
 *   {title: "Day 2", events: [{title: "Ouzhal Falls"}]}  → [{label: "", items: [{title: "Ouzhal Falls"}]}], at the block
 *   {title: "Day 3"}                                     → null (nothing to draw)
 */
function groupsOf(raw: any, here: Trail): { group: any; at: Trail }[] | null {
  if (Array.isArray(raw.groups)) {
    return raw.groups.map((group: any, gi: number) => ({ group, at: here.at("groups").at(gi) }));
  }
  const flat = firstList([raw.events, raw.items, raw.steps, raw.stops]);
  if (!flat) return null;
  return [{ group: { label: "", items: flat }, at: here }];
}

/**
 * One stop, or null when it has no title. The title may come as `name`, `label`, `activity` or `event`, and the line
 * under it as `note`, `text`, `description` or `detail`. A "time" too long for the time column is a heading the model
 * wrote in the wrong field, so when there's no title it becomes the title:
 *   {time: "Day 1: Nature & Lakes", description: "Botanical Gardens, then the lake"}
 *   → {title: "Day 1: Nature & Lakes", note: "Botanical Gardens, then the lake"}
 *   {time: "18:00", note: "Back to the hotel"} → null (a short time is a time: still no title)
 */
function readStop(it: any): Stop | null {
  if (!it || typeof it !== "object") return null;
  let title = firstText([it.title, it.name, it.label, it.activity, it.event], 80);
  let time = str(it.time, 60);
  const note = firstText([it.note, it.text, it.description, it.detail], 160);
  if (!title && time && time.length > TIME_MAX) {
    title = time;
    time = undefined;
  }
  if (!title) return null;
  return clean({ time: time?.slice(0, TIME_MAX), title, place: firstText([it.place, it.location], 60), note, icon: icon(it.icon) });
}
