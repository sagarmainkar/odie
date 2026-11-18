import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { fromBeforeInput, fromKey, gesture, liveUrl, sendInChat, signedInLine, toPage, upiDetails, upiLink, type LiveMsg, type Point } from "../signin";

export type LiveResult = { site: string; done: boolean };

/** The user's turn in Odie's browser (odie/signin/live.py), full screen: the page's frames, your taps and drags, your
 * own keyboard. Odie's model sees none of it. `chat`: Done says so in the chat ("I'm signed in to amazon.in."), and the
 * chat carries on; from Settings it only signs in. `start`: an address to open first (Settings → Sign in to a site).
 * `watch`: opened from the chat's Watch button while Odie browses (see Live). `who`: the assistant's name for the bar. */
export function LiveView(props: { tab: string; site: string; start?: string; chat: boolean; onClose: (r: LiveResult | null) => void; watch?: boolean; who?: string }) {
  return createPortal(<Live {...props} />, document.body);  // on the page itself: a card's backdrop filter would trap it
}

const ENDED: Record<string, string> = {
  idle: "Handed back to Odie after 15 minutes without a tap.",
  taken: "You took this over on another device.",
  closed: "Odie restarted. Open the sign-in again from the card.",
  off: "Signed-in browsing is off.",
  unpaired: "This device isn't paired with Odie.",
  lost: "The connection to Odie dropped. Open it again from the card.",
};

/** watch: Odie is at work in this tab; you see its page as it is, and nothing you do reaches it until Take control
 * (then Odie's next browser step waits). Two ways back: Hand back gives the page back and records nothing; "I signed
 * in" also records the site as one you're signed in to, as Done does, so ordering and paying there ask first.
 * who: the assistant's name for the bar. */
function Live({ tab, site, start, chat, onClose, watch = false, who = "Odie" }: { tab: string; site: string; start?: string; chat: boolean; onClose: (r: LiveResult | null) => void; watch?: boolean; who?: string }) {
  const [controlling, setControlling] = useState(!watch);
  const ws = useRef<WebSocket | null>(null);
  const [frame, setFrame] = useState<{ src: string; w: number; h: number } | null>(null);
  const [page, setPage] = useState({ url: "", title: "", loading: true });
  const [phase, setPhase] = useState<"connecting" | "live" | "busy" | "ended">("connecting");
  const [ended, setEnded] = useState("");
  const [upi, setUpi] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [address, setAddress] = useState(start ?? "");
  const [finishing, setFinishing] = useState(false);
  const [zoom, setZoom] = useState({ s: 1, x: 0, y: 0 });  // the app's viewport forbids native zoom: a desktop-shaped page can be pinched here
  const img = useRef<HTMLImageElement>(null);
  const keys = useRef<HTMLInputElement>(null);
  const fingers = useRef(new Map<number, Point>());
  const down = useRef<{ page: Point; at: Point; moved: boolean } | null>(null);
  const pinch = useRef<{ d0: number; s0: number; x0: number; y0: number; mid: Point } | null>(null);
  const opened = useRef(false);
  const typing = useRef(false);  // the address box has the user's own words: a page change doesn't overwrite them

  const send = (m: LiveMsg | { t: string }) => { if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(m)); };

  useEffect(() => {
    const sock = new WebSocket(liveUrl(tab, location));
    ws.current = sock;
    sock.onopen = () => sock.send(JSON.stringify({ t: "hello", w: Math.round(window.innerWidth), h: Math.max(480, Math.round(window.innerHeight - 112)), ...(watch ? { watch: true } : {}) }));
    sock.onmessage = (ev) => {
      let m: any;
      try { m = JSON.parse(ev.data); } catch { return; }
      if (m.t === "frame") { setFrame({ src: `data:image/jpeg;base64,${m.jpeg}`, w: Number(m.w) || 390, h: Number(m.h) || 844 }); setPhase("live"); }
      else if (m.t === "page") {
        setPage((p) => ({ url: m.url ?? p.url, title: m.title ?? p.title, loading: !!m.loading }));
        if (watch && typeof m.url === "string") setAddress((a) => (typing.current ? a : m.url));  // the page's own address
        if (start && !opened.current) { opened.current = true; sock.send(JSON.stringify({ t: "go", url: start })); }
      } else if (m.t === "busy") setPhase("busy");
      else if (m.t === "upi") setUpi(upiLink(String(m.url)));
      else if (m.t === "control") setControlling(true);
      else if (m.t === "error") { setNote(String(m.why || "The page didn't take that.")); window.setTimeout(() => setNote(""), 3000); }
      else if (m.t === "bye") { setEnded(String(m.why)); setPhase("ended"); }
    };
    sock.onclose = (e) => {
      setEnded((w) => w || (e.code === 4403 ? "off" : e.code === 4401 ? "unpaired" : "lost"));
      setPhase("ended");
    };
    const ping = window.setInterval(() => { if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ t: "ping" })); }, 20000);
    return () => { window.clearInterval(ping); sock.close(); };
  }, [tab]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {  // the phone's keyboard, through a hidden field (React's onBeforeInput isn't the native event)
    const el = keys.current;
    if (!el) return;
    const before = (e: Event) => {
      const ie = e as InputEvent;
      if (ie.isComposing) return;
      const m = fromBeforeInput(ie.inputType, ie.data, ie.dataTransfer?.getData("text/plain") ?? null);
      if (m) { send(m); e.preventDefault(); }
    };
    el.addEventListener("beforeinput", before);
    return () => el.removeEventListener("beforeinput", before);
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const box = () => img.current?.getBoundingClientRect();
  const onDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);  // watching too: pinch and pan the picture, nothing reaches the page
    fingers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (fingers.current.size === 2) {
      const [a, b] = [...fingers.current.values()];
      pinch.current = { d0: Math.hypot(a.x - b.x, a.y - b.y) || 1, s0: zoom.s, x0: zoom.x, y0: zoom.y, mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } };
      down.current = null;
      return;
    }
    const b = box();
    const p = b && frame ? toPage({ x: e.clientX, y: e.clientY }, b, frame) : null;
    down.current = p ? { page: p, at: { x: e.clientX, y: e.clientY }, moved: false } : null;
  };
  const onMove = (e: React.PointerEvent) => {
    const last = fingers.current.get(e.pointerId);
    if (!last) return;
    fingers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pz = pinch.current;
    if (pz && fingers.current.size === 2) {
      const [a, b] = [...fingers.current.values()];
      const s = Math.min(4, Math.max(1, pz.s0 * Math.hypot(a.x - b.x, a.y - b.y) / pz.d0));
      setZoom({ s, x: pz.x0 + (a.x + b.x) / 2 - pz.mid.x, y: pz.y0 + (a.y + b.y) / 2 - pz.mid.y });
      return;
    }
    const d = down.current;
    if (d && zoom.s > 1.01) {  // zoomed in: one finger moves the picture
      if (Math.hypot(e.clientX - d.at.x, e.clientY - d.at.y) > 8) d.moved = true;
      if (d.moved) setZoom((z) => ({ ...z, x: z.x + e.clientX - last.x, y: z.y + e.clientY - last.y }));
    }
  };
  const onUp = (e: React.PointerEvent) => {
    fingers.current.delete(e.pointerId);
    if (pinch.current) {
      if (fingers.current.size === 0) { pinch.current = null; if (zoom.s < 1.05) setZoom({ s: 1, x: 0, y: 0 }); }
      return;
    }
    const d = down.current;
    down.current = null;
    const b = box();
    if (!d || !b || !frame || d.moved) return;
    const up = toPage({ x: e.clientX, y: e.clientY }, b, frame, true) ?? d.page;
    const g = gesture(d.page, up);
    if (g.t === "drag" && zoom.s > 1.01) return;  // a pan of the zoomed picture, not a scroll
    if (!controlling) return;  // watching: the page is Odie's
    send(g);
  };

  async function finish(done: boolean) {
    setFinishing(true);
    try {
      const r = await fetch(`/api/browser/live/${encodeURIComponent(tab)}/${done ? "done" : "cancel"}`, { method: "POST" });
      const got = r.ok ? ((await r.json()) as { site?: string }) : {};
      const s = got.site || site;
      if (r.ok && chat && s) sendInChat(signedInLine(s, done));
      onClose(r.ok ? { site: s, done } : null);
    } catch {
      setFinishing(false);
      setNote("Odie didn't answer. Try again.");
    }
  }

  const host = (() => { try { return new URL(page.url).host.replace(/^www\./, ""); } catch { return site; } })();
  const pay = upi ? upiDetails(upi) : null;
  const bar = "w-10 h-10 rounded-full bg-white/12 grid place-items-center shrink-0 active:bg-white/25 disabled:opacity-40";
  return (
    <motion.div role="dialog" aria-modal="true" aria-label={watch ? `${who}'s browser` : `Sign in to ${site}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className="fixed inset-0 z-50 bg-[#0d0d10] text-white flex flex-col">
      {watch && !controlling ? (
        <div className="flex items-center gap-2 px-3 pt-[max(10px,env(safe-area-inset-top))] pb-2">
          <button onClick={() => { send({ t: "close" }); onClose(null); }} className="h-10 px-3 rounded-full text-ui font-semibold text-white/85 active:bg-white/15">Close</button>
          <div className="flex-1 min-w-0 text-center">
            <div className="text-ui font-semibold truncate">Watching {who}</div>
            <div className="text-caption text-white/55 truncate">{`${host || "…"}${page.title ? ` · ${page.title}` : ""}`}</div>
          </div>
          <button onClick={() => send({ t: "control" })} disabled={phase !== "live"} className="h-10 px-4 rounded-full bg-white text-black text-ui font-bold disabled:opacity-40">Take control</button>
        </div>
      ) : (
      <>
      <div className="flex items-center gap-2 px-3 pt-[max(10px,env(safe-area-inset-top))] pb-2">
        {watch
          ? <button onClick={() => finish(true)} disabled={finishing} className="h-10 px-3 rounded-full text-ui font-semibold text-white/85 active:bg-white/15">I signed in</button>
          : <button onClick={() => finish(false)} disabled={finishing} className="h-10 px-3 rounded-full text-ui font-semibold text-white/85 active:bg-white/15">Cancel</button>}
        <div className="flex-1 min-w-0 text-center">
          <div className="text-ui font-semibold truncate flex items-center justify-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
            {host || site}
          </div>
          <div className="text-caption text-white/55 truncate">{page.loading ? "Loading…" : page.title || "Your turn: Odie can't see this"}</div>
        </div>
        <button onClick={() => finish(!watch)} disabled={finishing || phase !== "live"} className="h-10 px-4 rounded-full bg-white text-black text-ui font-bold disabled:opacity-40">
          {finishing ? "…" : watch ? `Hand back to ${who}` : "Done"}
        </button>
      </div>
      <div className="flex items-center gap-2 px-3 pb-2">
        <button aria-label="Back" onClick={() => send({ t: "back" })} disabled={phase !== "live"} className={bar}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M15 18l-6-6 6-6" /></svg>
        </button>
        <button aria-label="Forward" onClick={() => send({ t: "forward" })} disabled={phase !== "live"} className={bar}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M9 18l6-6-6-6" /></svg>
        </button>
        <button aria-label="Reload" onClick={() => send({ t: "reload" })} disabled={phase !== "live"} className={bar}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" /></svg>
        </button>
        {start !== undefined || watch ? (
          <form className="flex-1 min-w-0" onSubmit={(e) => { e.preventDefault(); if (address.trim()) send({ t: "go", url: address.trim() }); }}>
            <input value={address} onChange={(e) => { typing.current = true; setAddress(e.target.value); }} onBlur={() => { typing.current = false; }} inputMode="url" autoCapitalize="off" autoCorrect="off" spellCheck={false}
              aria-label="Address" placeholder="amazon.in" className="w-full h-10 rounded-full bg-white/12 px-4 text-ui outline-none placeholder:text-white/40" />
          </form>
        ) : <div className="flex-1 text-caption leading-4 text-white/55">You type your password and codes yourself. Odie doesn't see them.</div>}
        <button aria-label="Keyboard" onClick={() => { const k = keys.current; if (!k) return; if (document.activeElement === k) k.blur(); else k.focus(); }}
          disabled={phase !== "live"} className={bar}>
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10" /></svg>
        </button>
        {zoom.s > 1.01 && <button onClick={() => setZoom({ s: 1, x: 0, y: 0 })} className="h-10 px-3 rounded-full bg-white/12 text-small font-semibold">1×</button>}
      </div>
      </>
      )}
      <input ref={keys} aria-hidden tabIndex={-1} autoCapitalize="off" autoCorrect="off" autoComplete="off" spellCheck={false}
        className="absolute -left-[200px] top-0 w-px h-px opacity-0"
        onKeyDown={(e) => { const m = fromKey(e.key); if (m) { e.preventDefault(); send(m); } }}
        onCompositionEnd={(e) => { if (e.data) send({ t: "text", s: e.data }); e.currentTarget.value = ""; }}
        onPaste={(e) => { const t = e.clipboardData.getData("text/plain"); if (t) { e.preventDefault(); send({ t: "text", s: t }); } }}
        onInput={(e) => { if (!(e.nativeEvent as InputEvent).isComposing) e.currentTarget.value = ""; }} />
      <div className="relative flex-1 min-h-0 flex items-center justify-center overflow-hidden" style={{ touchAction: "none" }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
        {frame && <img ref={img} src={frame.src} alt="" draggable={false}
          style={{ transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.s})`, transformOrigin: "center" }}
          className="max-w-full max-h-full object-contain select-none pointer-events-none" />}
        {phase === "connecting" && <div className="text-ui text-white/70 flex items-center gap-2"><span className="spinner" />Opening Odie's browser…</div>}
        {phase === "busy" && (
          <div className="absolute inset-0 grid place-items-center bg-black/70 p-6 text-center">
            <div className="flex flex-col items-center gap-3">
              <div className="text-body font-semibold">In use on another device</div>
              <button onClick={() => send({ t: "take" })} className="h-11 px-5 rounded-full bg-white text-black text-body font-bold">Take over here</button>
              <button onClick={() => onClose(null)} className="text-ui text-white/70 h-10">Close</button>
            </div>
          </div>
        )}
        {phase === "ended" && !finishing && (
          <div className="absolute inset-0 grid place-items-center bg-black/75 p-6 text-center">
            <div className="flex flex-col items-center gap-3 max-w-[300px]">
              <div className="text-body leading-[22px]">{ENDED[ended] ?? "The sign-in ended."}</div>
              <button onClick={() => onClose(null)} className="h-11 px-5 rounded-full bg-white text-black text-body font-bold">Close</button>
            </div>
          </div>
        )}
        {note && <div className="absolute top-3 left-1/2 -translate-x-1/2 rounded-full bg-black/80 px-4 py-2 text-small">{note}</div>}
      </div>
      {upi && pay && (
        <div className="px-3 pt-2 pb-[max(12px,env(safe-area-inset-bottom))]">
          <a href={upi} className="flex items-center justify-center gap-2 h-12 rounded-full bg-[#1fa463] text-white text-body font-bold">
            Pay {pay.amount ? `₹${pay.amount} ` : ""}in your UPI app
          </a>
          <div className="text-center text-caption text-white/55 mt-1.5">{pay.payee ? `To ${pay.payee}. ` : ""}You approve it there, with your PIN.</div>
        </div>
      )}
    </motion.div>
  );
}
