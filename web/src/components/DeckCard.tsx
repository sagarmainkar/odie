import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { clampPan, deckLine, pinchScale, step, swipe, visible, type DeckPage } from "../deck";
import { size } from "../files";
import { mediaUrl, type Media } from "../media";
import { ShareFile } from "./ShareButton";
import { Icon, Tile } from "./Tile";

type Download = { id: string; filename: string; size: number; label: string };

function downloads(m: Media): Download[] {
  const name = m.filename || m.title;
  const own: Download = { id: m.id, filename: name, size: m.size, label: name.toLowerCase().endsWith(".pdf") ? "PDF" : "PowerPoint" };
  const pptx = m.deck?.pptx;
  return pptx ? [own, { id: pptx.id, filename: pptx.filename, size: pptx.size, label: "PowerPoint" }] : [own];
}

function DownloadButton({ d, dark = false }: { d: Download; dark?: boolean }) {
  return (
    <a href={mediaUrl(d)} download={d.filename} onClick={(e) => e.stopPropagation()} aria-label={`Download ${d.filename}, ${d.label}, ${size(d.size)}`}
      className={`h-10 px-3.5 rounded-full flex items-center gap-2 text-[13.5px] font-semibold shrink-0 ${dark ? "bg-white/15 text-white" : "bg-well text-ink-2 active:bg-line"}`}>
      <span className="rotate-180 grid place-items-center"><Icon name="up" size={15} /></span>
      {d.label}<span className={`font-normal ${dark ? "text-white/70" : "text-muted"}`}>{size(d.size)}</span>
    </a>
  );
}

/** A designed deck under the reply: a strip of slide previews (a tap opens the viewer) and its downloads. */
export function DeckCard({ m }: { m: Media }) {
  const [open, setOpen] = useState<number | null>(null);
  const deck = m.deck!;
  const { shown, more } = visible(deck.pages);
  const files = downloads(m);
  const title = (m.title || m.filename || "Deck").replace(/ · PowerPoint$/, "");
  return (
    <div className="glass rounded-[22px] w-full max-w-[440px] overflow-hidden" data-media="deck">
      <div className="flex items-center gap-3 px-3.5 pt-3 pb-2.5">
        <Tile icon="chart" color="orange" small />
        <span className="flex-1 min-w-0">
          <b className="block text-[14.5px] font-semibold leading-5 truncate">{title}</b>
          <span className="block text-[12.5px] text-muted">{deckLine(m)}</span>
        </span>
      </div>
      {shown.length > 0 && (
        <div className="flex gap-2 overflow-x-auto no-scrollbar snap-x snap-mandatory px-3.5 pb-1">
          {shown.map((p, i) => (
            <button key={p.thumb} onClick={() => setOpen(i)} aria-label={`Open slide ${i + 1}`} className="relative shrink-0 snap-start">
              <img src={mediaUrl({ id: p.thumb })} alt="" loading="lazy" className="w-[168px] aspect-video rounded-[12px] object-cover bg-well border border-line" />
              <span className="absolute left-1.5 bottom-1.5 px-1.5 rounded-md bg-black/55 text-white text-[10.5px] font-semibold leading-[17px]">{i + 1}</span>
            </button>
          ))}
          {more > 0 && (
            <button onClick={() => setOpen(shown.length)} aria-label={`${more} more slides`}
              className="shrink-0 w-[72px] aspect-[72/94.5] rounded-[12px] bg-well border border-line text-[14px] font-semibold text-muted snap-start">+{more}</button>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2 px-3.5 pt-2 pb-3">
        {files.map((d) => <DownloadButton key={d.id} d={d} />)}
        <ShareFile file={files[0]} />
      </div>
      {deck.note && <div className="px-3.5 pb-3 -mt-1 text-[12px] leading-[16px] text-muted">{deck.note}</div>}
      {createPortal(  // on the page itself: a card's backdrop filter would trap a fixed overlay inside the card
        <AnimatePresence>{open !== null && <DeckViewer pages={deck.pages} at={open} setAt={setOpen} files={files} title={title} />}</AnimatePresence>,
        document.body)}
    </div>
  );
}

function DeckViewer({ pages, at, setAt, files, title }: { pages: DeckPage[]; at: number; setAt: (i: number | null) => void; files: Download[]; title: string }) {
  type Gesture = { mode: "swipe" | "pan" | "pinch"; x: number; y: number; d0: number; base: number; ox: number; oy: number };
  const touch = useRef<Gesture | null>(null);
  const lastTap = useRef(0);
  const img = useRef<HTMLImageElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const [zoom, setZoom] = useState({ s: 1, x: 0, y: 0 });  // the app's viewport forbids native zoom, so the viewer has its own
  useEffect(() => setZoom({ s: 1, x: 0, y: 0 }), [at]);
  const go = (by: number) => setAt(step(at, by, pages.length));
  const dist = (t: React.TouchList) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  const size = () => ({ w: img.current?.clientWidth ?? 0, h: img.current?.clientHeight ?? 0 });
  function start(e: React.TouchEvent) {
    const t = e.touches;
    if (t.length >= 2) touch.current = { mode: "pinch", x: 0, y: 0, d0: dist(t), base: zoom.s, ox: zoom.x, oy: zoom.y };
    else touch.current = { mode: zoom.s > 1 ? "pan" : "swipe", x: t[0].clientX, y: t[0].clientY, d0: 0, base: zoom.s, ox: zoom.x, oy: zoom.y };
  }
  function move(e: React.TouchEvent) {
    const g = touch.current;
    if (!g) return;
    const { w, h } = size();
    if (g.mode === "pinch" && e.touches.length >= 2) {
      const sc = pinchScale(g.base, g.d0, dist(e.touches));
      setZoom((z) => ({ s: sc, ...clampPan(z.x, z.y, sc, w, h) }));
    } else if (g.mode === "pan") {
      const p = clampPan(g.ox + e.touches[0].clientX - g.x, g.oy + e.touches[0].clientY - g.y, zoom.s, w, h);
      setZoom((z) => ({ ...z, ...p }));
    }
  }
  function end(e: React.TouchEvent) {
    const g = touch.current;
    touch.current = e.touches.length ? touch.current : null;
    if (!g || g.mode === "pinch" || e.touches.length) return;
    const dx = e.changedTouches[0].clientX - g.x, dy = e.changedTouches[0].clientY - g.y;
    if (Math.abs(dx) < 10 && Math.abs(dy) < 10) {  // a tap, zoomed or not: two in a row zoom in, or back out
      const now = Date.now();
      if (now - lastTap.current < 320) setZoom((z) => (z.s > 1 ? { s: 1, x: 0, y: 0 } : { s: 2.5, x: 0, y: 0 }));
      lastTap.current = now;
      return;
    }
    if (g.mode === "swipe") {
      const by = swipe(dx, dy);
      if (by) go(by);
    }
  }
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
  }, [at, pages.length]);  // eslint-disable-line react-hooks/exhaustive-deps
  const keep = (e: React.MouseEvent) => e.stopPropagation();
  const p = pages[at];
  return (
    <motion.div role="dialog" aria-modal="true" aria-label={`${title}, slide ${at + 1} of ${pages.length}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/92 flex flex-col" onClick={() => setAt(null)}
      onTouchStart={start} onTouchMove={move} onTouchEnd={end}>
      <div className="flex items-center gap-3 px-4 pt-[max(16px,env(safe-area-inset-top))] pb-3 text-white">
        <div className="flex-1 min-w-0 text-[15px] font-semibold truncate" onClick={keep}>{title}</div>
        <span className="text-[13px] text-white/70 shrink-0 tabular-nums">{at + 1} / {pages.length}</span>
        <button ref={close} onClick={(e) => { keep(e); setAt(null); }} aria-label="Close" className="w-9 h-9 rounded-full bg-white/15 grid place-items-center shrink-0">✕</button>
      </div>
      <div className="flex-1 min-h-0 flex items-center justify-center px-2 overflow-hidden" style={{ touchAction: "none" }}>
        {p && <img ref={img} key={p.view} src={mediaUrl({ id: p.view })} alt={`Slide ${at + 1}`} onClick={keep} draggable={false}
          style={{ transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.s})`, transition: touch.current ? "none" : "transform .18s ease-out" }}
          className="max-w-full max-h-full object-contain rounded-[8px] shadow-2xl select-none" />}
        {pages[at + 1] && <link rel="preload" as="image" href={mediaUrl({ id: pages[at + 1].view })} />}
      </div>
      <div className="flex flex-col gap-3 px-4 pt-3 pb-[max(16px,env(safe-area-inset-bottom))] text-white">
        <div className="flex items-center justify-between">
          <button onClick={(e) => { keep(e); go(-1); }} disabled={at === 0} aria-label="Previous slide" className="w-11 h-11 rounded-full bg-white/15 disabled:opacity-30">‹</button>
          <span className="text-[12.5px] text-white/55">Swipe for the next slide</span>
          <button onClick={(e) => { keep(e); go(1); }} disabled={at === pages.length - 1} aria-label="Next slide" className="w-11 h-11 rounded-full bg-white/15 disabled:opacity-30">›</button>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {files.map((d) => <DownloadButton key={d.id} d={d} dark />)}
          <ShareFile file={files[0]} dark />
        </div>
      </div>
    </motion.div>
  );
}
