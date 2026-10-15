import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import type { ReactNode } from "react";

/** A section whose body folds away: tap the title row (chevron turns) and the body slides open or shut. */
export function Collapse({ title, summary, defaultOpen = false, children }: { title: ReactNode; summary?: ReactNode; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="flex flex-col gap-2">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex items-center gap-2 px-1.5 min-h-10 text-left">
        <span className="text-[13px] leading-5 font-bold text-muted">{title}</span>
        <span className="ml-auto flex items-center gap-2 text-[12.5px] text-dim">
          {summary}
          <motion.svg animate={{ rotate: open ? 90 : 0 }} transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
            width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 6l6 6-6 6" />
          </motion.svg>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="body" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.26, ease: [0.2, 0.8, 0.2, 1] }} className="overflow-hidden">
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
