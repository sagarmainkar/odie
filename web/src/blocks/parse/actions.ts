import { firstList, firstText, keepFirst, type Trail } from "./fields";

export type ActionsBlock = { type: "actions"; items: { label: string; run: string }[] };

/**
 * actions: up to 3 buttons that send a message. Models also write `buttons` for items, `text` for label and `ask` or
 * `message` for run; a button without both a label and a message is dropped.
 *   {type: "actions", buttons: [{text: "Weather", ask: "Goa weather this week"}, {label: "Empty"}]}
 *   → {type: "actions", items: [{label: "Weather", run: "Goa weather this week"}]}
 * Dropped: no list, or no usable button.
 */
export function readActions(raw: any, here: Trail): ActionsBlock | null {
  const list = firstList([raw.items, raw.buttons]);
  if (!list) return here.drop("actions needs items");
  const items: { label: string; run: string }[] = [];
  list.forEach((item: any, i: number) => {
    const label = firstText([item?.label, item?.text], 40);
    const run = firstText([item?.run, item?.ask, item?.message], 300);
    if (!label || !run) {
      here.at("items").at(i).drop("button needs a label and a run message");
      return;
    }
    items.push({ label, run });
  });
  if (!items.length) return here.drop("actions has no usable button");
  return { type: "actions", items: keepFirst(items, 3, here, "buttons") };
}
