import { motion } from "framer-motion";
import { useState, type ReactNode } from "react";
import { ToBody } from "./ToBody";

/** A drawn block (blocks, a chart, a diagram) with an expand corner: a tap opens the same block full screen, with
 * bigger type, room to scroll sideways, and pinch-zoom (the page allows it). Pictures and drawings have their own
 * large views. `label` names what opens, for the button. */
export function Enlarge({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative group" data-visual={label.toLowerCase()}>
      {children}
      <button type="button" onClick={() => setOpen(true)} aria-label={`Open ${label} large`} data-share-hide
        className="absolute top-1 right-1 w-9 h-9 rounded-full bg-[var(--t-surface-2)] border border-line text-muted grid place-items-center opacity-70 active:opacity-100 shadow-sm">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
        </svg>
      </button>
      {open && (  /* the portal only while open: a reply rendered to plain HTML (the sample chat) has no document */
        <ToBody>
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} role="dialog" aria-label={label}
            className="fixed inset-0 z-50 bg-[var(--t-surface-2)] flex flex-col safe-top safe-bottom">
            <div className="flex items-center justify-between px-4 py-2">
              <span className="text-[13px] font-semibold text-muted">{label}</span>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close" className="w-9 h-9 rounded-full bg-well text-ink grid place-items-center text-[18px]">×</button>
            </div>
            <div className="enlarged flex-1 overflow-auto px-4 pb-6 [touch-action:pan-x_pan-y_pinch-zoom]">
              <div className="md min-w-full">{children}</div>
            </div>
          </motion.div>
        </ToBody>
      )}
    </div>
  );
}
