import { clean, firstList, firstText, keepFirst, type Trail } from "./fields";

export type ChecklistItem = { text: string; group?: string };
/** path: where the checklist sits in its fence ("2", "0.children.1"), so its ticks can be saved and found again.
 *  ticked: the items the model said are already done (the starting ticks, before the user taps). */
export type ChecklistBlock = { type: "checklist"; title?: string; numbered: boolean; items: ChecklistItem[]; ticked: number[]; path: string };

const MAX_ITEMS = 40;

/**
 * checklist: things to do or pack, or steps to follow; the user ticks them off and the ticks are saved.
 * - items (also `tasks`, `steps`), up to 40: a string, or {text (also `title`/`label`/`name`), group (also
 *   `section`/`category`), done: true for one already done}. Items with the same group are drawn under one heading.
 * - groups: [{label (also `title`/`name`), items: [...]}] works too: each item takes its group's label.
 * - numbered: true numbers the items (also `ordered`). title: optional (also `label`).
 *   {type: "checklist", title: "Ooty", groups: [{label: "Clothes", items: ["Jacket", {title: "Socks", done: true}]}], ordered: true}
 *   → {type: "checklist", title: "Ooty", numbered: true, items: [{text: "Jacket", group: "Clothes"}, {text: "Socks", group: "Clothes"}],
 *      ticked: [1], path: "0"}
 * Dropped: no item with text (and each item without text, with a note).
 */
export function readChecklist(raw: any, here: Trail): ChecklistBlock | null {
  const found = collectItems(raw, here);
  if (!found.length) return here.drop("checklist has no item with text");
  const kept = keepFirst(found, MAX_ITEMS, here, "items");

  const items: ChecklistItem[] = [];
  const ticked: number[] = [];
  kept.forEach((item, i) => {
    items.push(clean({ text: item.text, group: item.group }));
    if (item.done) ticked.push(i);
  });
  const numbered = raw.numbered === true || raw.ordered === true;
  const title = firstText([raw.title, raw.label], 80);
  return clean({ type: "checklist" as const, title, numbered, items, ticked, path: here.path });
}

type Found = { text: string; group?: string; done: boolean };

/** The items wherever the model put them: a flat list (items, tasks, steps), or lists inside groups. */
function collectItems(raw: any, here: Trail): Found[] {
  const found: Found[] = [];
  const flat = firstList([raw.items, raw.tasks, raw.steps]);
  flat?.forEach((item, i) => {
    const read = readItem(item, undefined);
    if (read) found.push(read);
    else here.at("items").at(i).drop("item has no text");
  });

  const groups = firstList([raw.groups, raw.sections]) ?? [];
  groups.forEach((g: any, gi) => {
    const label = firstText([g?.label, g?.title, g?.name], 60);
    const list = firstList([g?.items, g?.tasks]) ?? [];
    list.forEach((item, i) => {
      const read = readItem(item, label);
      if (read) found.push(read);
      else here.at("groups").at(gi).at("items").at(i).drop("item has no text");
    });
  });
  return found;
}

/** One item → its text, group and done flag; null when it has no text.
 *  "Passport" → {text: "Passport", done: false};  {label: "Socks", category: "Clothes", done: true} → {text: "Socks", group: "Clothes", done: true} */
function readItem(item: any, groupLabel: string | undefined): Found | null {
  if (typeof item === "string") {
    const text = firstText([item], 160);
    if (!text) return null;
    return { text, group: groupLabel, done: false };
  }
  if (!item || typeof item !== "object") return null;
  const text = firstText([item.text, item.title, item.label, item.name], 160);
  if (!text) return null;
  const group = firstText([item.group, item.section, item.category], 60) ?? groupLabel;
  return { text, group, done: item.done === true || item.checked === true };
}
