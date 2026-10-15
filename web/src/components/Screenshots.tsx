import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { mediaUrl, type Media } from "../media";
import { site } from "../screenshots";

/** The page the browser is on, large, while the reply is being written (like watching it work). */
export function LiveBrowser({ shot, count }: { shot: Media; count: number }) {
  return (
    <div className="glass rounded-[22px] overflow-hidden w-full max-w-[460px]" data-media="browser-live">
      <div className="flex items-center gap-2 px-3.5 py-2.5 text-[12.5px] font-semibold text-muted">
        <span className="relative flex w-2 h-2"><span className="absolute inline-flex h-full w-full rounded-full bg-ember opacity-60 animate-ping" /><span className="relative inline-flex w-2 h-2 rounded-full bg-ember" /></span>
        <span className="truncate">Browsing {site(shot.url ?? "")}</span>
        {count > 1 && <span className="ml-auto shrink-0 text-dim">{count} pages</span>}
      </div>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.img key={shot.id} src={mediaUrl(shot)} alt={shot.title} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }} className="block w-full aspect-[1280/900] object-cover object-top bg-well" />
      </AnimatePresence>
      {shot.step && <div className="px-3.5 py-2 text-[13px] text-ink-2 truncate">{shot.step}</div>}
    </div>
  );
}

/** Afterwards: the pages as a row of thumbnails; a tap opens them full screen. */
export function ScreenshotStrip({ shots }: { shots: Media[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-1 px-1 pb-0.5" data-media="browser-strip">
        {shots.map((s, i) => (
          <button key={s.id} onClick={() => setOpen(i)} aria-label={`Open screenshot: ${s.title}`} className="shrink-0 w-[132px] text-left">
            <img src={mediaUrl(s)} alt="" loading="lazy" className="w-[132px] h-[92px] rounded-[14px] object-cover object-top bg-well border border-line" />
            <div className="mt-1 text-[11.5px] leading-[15px] text-muted truncate">{site(s.url ?? "")}</div>
          </button>
        ))}
      </div>
      <AnimatePresence>{open !== null && <Viewer shots={shots} at={open} setAt={setOpen} />}</AnimatePresence>
    </>
  );
}

function Viewer({ shots, at, setAt }: { shots: Media[]; at: number; setAt: (i: number | null) => void }) {
  const s = shots[at];
  const touch = useRef<number | null>(null);
  const close = useRef<HTMLButtonElement>(null);
  const go = (d: number) => setAt(Math.max(0, Math.min(shots.length - 1, at + d)));
  useEffect(() => {  // focus moves in, the page behind stays put, and focus goes back when it closes
    const before = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    close.current?.focus();
    return () => { document.body.style.overflow = overflow; before?.focus?.(); };
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setAt(null); else if (e.key === "ArrowRight") go(1); else if (e.key === "ArrowLeft") go(-1); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [at, shots.length]);  // eslint-disable-line react-hooks/exhaustive-deps
  const keep = (e: React.MouseEvent) => e.stopPropagation();  // a tap on the picture or a control stays; anywhere else closes
  return (
    <motion.div role="dialog" aria-modal="true" aria-label="Screenshot" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/90 flex flex-col" onClick={() => setAt(null)}
      onTouchStart={(e) => { touch.current = e.touches[0].clientX; }}
      onTouchEnd={(e) => { if (touch.current !== null) { const dx = e.changedTouches[0].clientX - touch.current; if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1); } touch.current = null; }}>
      <div className="flex items-start gap-3 px-4 pt-[max(16px,env(safe-area-inset-top))] pb-3 text-white">
        <div className="flex-1 min-w-0" onClick={keep}>
          <div className="text-[15px] font-semibold truncate">{s.page_title || site(s.url ?? "")}</div>
          {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="block text-[12.5px] text-white/70 truncate">{s.url}</a>}
        </div>
        <span className="text-[12.5px] text-white/60 shrink-0 mt-0.5">{at + 1} / {shots.length}</span>
        <button ref={close} onClick={(e) => { keep(e); setAt(null); }} aria-label="Close" className="w-9 h-9 -mt-1 rounded-full bg-white/15 grid place-items-center shrink-0">✕</button>
      </div>
      <div className="flex-1 min-h-0 flex items-center justify-center px-2">
        <img src={mediaUrl(s)} alt={s.title} onClick={keep} className="max-w-full max-h-full object-contain rounded-[10px]" />
      </div>
      <div className="flex items-center justify-between px-6 py-4 pb-[max(16px,env(safe-area-inset-bottom))] text-white">
        <button onClick={(e) => { keep(e); go(-1); }} disabled={at === 0} aria-label="Previous screenshot" className="w-11 h-11 rounded-full bg-white/15 disabled:opacity-30">‹</button>
        <span className="text-[13px] text-white/80 truncate px-3">{s.step}</span>
        <button onClick={(e) => { keep(e); go(1); }} disabled={at === shots.length - 1} aria-label="Next screenshot" className="w-11 h-11 rounded-full bg-white/15 disabled:opacity-30">›</button>
      </div>
    </motion.div>
  );
}
