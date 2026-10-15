// Containers draw blocks that were already drawn: they only arrange them (side by side, in a titled card, in a grid).
import { AnimatePresence, motion } from "framer-motion";
import { useState, type ReactNode } from "react";
import { InCard } from "./InCard";
import { InlineText } from "./InlineText";
import { wideColumns } from "./wideColumns";

// Kinds that keep their own width in a row (a pill, a link); everything else shares the row's width.
const OWN_WIDTH_KINDS = ["badge", "button", "link"];

/** Side by side, wrapping onto the next line when there's no room (each wide part wants about 140px). */
export function Row({ kinds, children }: { kinds: string[]; children: ReactNode[] }) {
  return (
    <div className="flex flex-wrap items-stretch gap-2 my-2">
      {children.map((child, i) => {
        const ownWidth = OWN_WIDTH_KINDS.includes(kinds[i]);
        const place = ownWidth ? "flex-none self-center" : "flex-[1_1_140px] min-w-0 [&>*]:h-full";
        return <div key={i} className={`${place} [&>*]:my-0`}>{child}</div>;
      })}
    </div>
  );
}

/** Two columns on a phone; up to four when the block is wide (wideColumns). */
export function Grid({ children }: { children: ReactNode[] }) {
  return (
    <div className={`grid grid-cols-2 ${wideColumns(children.length)} gap-2 my-2`}>
      {children.map((child, i) => <div key={i} className="min-w-0 [&>*]:my-0 [&>*]:h-full">{child}</div>)}
    </div>
  );
}

/** A titled card. collapsed: an accordion that starts closed; tap the title to open it. */
export function Section({ title, collapsed, children }: { title?: string; collapsed: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(!collapsed);
  const body = <InCard.Provider value={true}><div className="flex flex-col">{children}</div></InCard.Provider>;

  if (!collapsed) {
    return (
      <div className="glass glass-solid rounded-[24px] px-4 py-3.5 my-2">
        {title && <div className="text-[17px] leading-[23px] font-bold tracking-[-0.01em] mb-1"><InlineText text={title} /></div>}
        {body}
      </div>
    );
  }
  return (
    <div className="glass glass-solid rounded-[24px] px-4 my-2">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="w-full flex items-center gap-2 py-3.5 text-left">
        <span className="flex-1 min-w-0 text-[16px] leading-[22px] font-bold tracking-[-0.01em]"><InlineText text={title ?? ""} /></span>
        <motion.svg animate={{ rotate: open ? 90 : 0 }} transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }} className="shrink-0 text-muted"
          width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 6l6 6-6 6" />
        </motion.svg>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="body" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.2, 0.8, 0.2, 1] }} className="overflow-hidden">
            <div className="pb-3.5">{body}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
