import { useContext } from "react";
import { Icon } from "../components/Tile";
import { InCard } from "./InCard";
import { InlineText } from "./InlineText";
import type { ChecklistItem } from "./parse";
import { useSavedTicks } from "./SavedPlace";

type Props = { title?: string; numbered: boolean; items: ChecklistItem[]; ticked: number[]; path: string };

/** Things to do or pack: tap an item to tick it off ("3 of 9 done" above). Items with a group sit under its heading.
 *  In a chat reply the ticks are saved, so they're still there after a reload and on the laptop. */
export function Checklist({ title, numbered, items, ticked, path }: Props) {
  const inCard = useContext(InCard);
  const [ticks, tap] = useSavedTicks(path, ticked, items.length);
  const done = ticks.length;
  const allDone = done === items.length;
  const frame = inCard ? "my-2" : "glass glass-solid rounded-[20px] px-4 py-3 my-2";

  return (
    <div className={frame}>
      <div className="flex items-baseline gap-2">
        {title && <span className="flex-1 min-w-0 text-[15px] leading-[21px] font-bold"><InlineText text={title} /></span>}
        <span className={`${title ? "" : "flex-1"} text-[12.5px] font-semibold tabular-nums whitespace-nowrap ${allDone ? "text-good" : "text-muted"}`} aria-live="polite">
          {allDone ? "All done" : `${done} of ${items.length} done`}
        </span>
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-ember-tint overflow-hidden">
        <div className="h-full rounded-full bg-good transition-[width] duration-300" style={{ width: `${(done / items.length) * 100}%` }} />
      </div>
      {/* divs, not ul/li: inside a reply, Markdown styles would add bullets */}
      <div className="mt-1">
        {items.map((item, i) => (
          <div key={i}>
            {startsGroup(items, i) && <div className="pt-3 pb-0.5 text-[12px] font-bold text-muted"><InlineText text={item.group!} /></div>}
            <ItemRow text={item.text} number={numbered ? i + 1 : null} ticked={ticks.includes(i)} onTap={() => tap(i)} />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Whether item i starts a new group heading: it has a group, and the item before it has a different one (or none).
 *  [Jacket (Clothes), Socks (Clothes), Passport (Papers)]: at 0 → yes, at 1 → no, at 2 → yes */
function startsGroup(items: ChecklistItem[], i: number): boolean {
  const group = items[i].group;
  if (!group) return false;
  return items[i - 1]?.group !== group;
}

function ItemRow({ text, number, ticked, onTap }: { text: string; number: number | null; ticked: boolean; onTap: () => void }) {
  const circle = ticked ? "bg-good border-good text-white" : "border-line-2 text-muted";
  return (
    <button type="button" role="checkbox" aria-checked={ticked} onClick={onTap}
      className="w-full flex items-start gap-3 py-2 text-left active:opacity-70">
      <span className={`mt-px w-[22px] h-[22px] shrink-0 rounded-full border-2 grid place-items-center text-[11px] font-bold tabular-nums transition-colors ${circle}`}>
        {ticked ? <Icon name="check" size={13} stroke={3} /> : number}
      </span>
      <span className={`flex-1 min-w-0 text-[15px] leading-[22px] transition-colors ${ticked ? "line-through decoration-1 text-muted" : "text-ink"}`}>
        <InlineText text={text} />
      </span>
    </button>
  );
}
