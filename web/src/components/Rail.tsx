import type { Tab } from "../App";
import type { Caps } from "../capabilities";
import { railItems, railTabFor } from "../layout";
import { Orb, type OrbState } from "./Orb";
import { Icon } from "./Tile";

/** The desktop's tabs: a slim rail down the left edge (hidden below 1024px, where Today is home and its links lead on).
 *  Tapping the tab already open tells that screen (Chat jumps to the latest message). */
export function Rail({ tab, caps, pending, orb, updateReady = false }: { tab: Tab; caps: Caps; pending: number; orb: OrbState; updateReady?: boolean }) {
  const current = railTabFor(tab);
  function reselect(item: Tab) {
    if (item === current) window.dispatchEvent(new CustomEvent("odie:tab-reselect", { detail: item }));
  }
  return (
    <nav aria-label="Tabs" className="hidden lg:flex shrink-0 w-[84px] h-full flex-col items-center gap-1.5 safe-top pb-5 border-r border-line bg-overlay backdrop-blur-xl">
      <a href="#today" aria-label="Today" className="mb-4 flex"><Orb size={38} state={orb} /></a>
      {railItems(caps).map((item) => {
        const on = item.tab === current;
        const waiting = item.tab === "chat" && pending > 0;
        const newVersion = item.tab === "settings" && updateReady;  // a dot: Settings has an Update Odie button
        return (
          <a key={item.tab} href={`#${item.tab}`} onClick={() => reselect(item.tab)} aria-current={on ? "page" : undefined}
            className={`relative w-[68px] flex flex-col items-center gap-1 py-2 rounded-[18px] text-[11.5px] font-semibold transition-colors ${on ? "glass glass-solid text-ink" : "text-muted hover:bg-well hover:text-ink-2"}`}>
            <Icon name={item.icon} size={20} />
            {item.label}
            {waiting && <span className="absolute top-1 right-3 min-w-[18px] h-[18px] px-1 rounded-full bg-ember text-on-ember text-[11px] font-bold grid place-items-center">{pending}</span>}
            {newVersion && <span aria-label="Update ready" className="absolute top-2 right-4 w-2.5 h-2.5 rounded-full bg-gold ring-2 ring-gold-tint" />}
          </a>
        );
      })}
    </nav>
  );
}
