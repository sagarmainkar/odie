import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState, type ReactNode, type Ref } from "react";
import { getJSON, postJSON, todayISO } from "../api";
import { groupThreads, sameAsTopRow, whenText, type Thread } from "../threads";
import { usePick } from "../pick";
import { onApple, shortcutText, showsThreadsPill } from "../threadsSidebar";
import { Icon } from "./Tile";
import { ToBody } from "./ToBody";

function Star({ on }: { on: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill={on ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
      <path d="m12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4l-4.8 2.5.9-5.4-3.9-3.8 5.4-.8z" />
    </svg>
  );
}

function threadsUrl(q: string): string {
  const query = q.trim();
  return query ? `/api/threads?q=${encodeURIComponent(query)}` : "/api/threads";
}

/** The threads list and its search. It loads while `active` (the sheet is open; the sidebar always), and again when
 *  `reload` changes (the sidebar bumps it after a reply, so a new thread shows up). */
function useThreadList(active: boolean, reload: number) {
  const [list, setList] = useState<Thread[] | null>(null);
  const [q, setQ] = useState("");
  const pick = usePick();  // the list is the picked personality's (getJSON names it): it loads again on a switch
  useEffect(() => { setList(null); setQ(""); }, [pick]);  // never the other one's threads while the new list loads
  useEffect(() => {
    if (!active) return;
    const id = setTimeout(() => {
      getJSON<{ threads: Thread[] }>(threadsUrl(q)).then((d) => setList(d.threads)).catch(() => setList([]));
    }, q ? 250 : 0);
    return () => clearTimeout(id);
  }, [active, q, reload, pick]);

  async function pin(t: Thread) {
    setList((l) => l?.map((x) => (x.id === t.id ? { ...x, pinned: !t.pinned } : x)) ?? l);
    try { await postJSON(`/api/threads/${t.id}/pin`, { pinned: !t.pinned }); } catch { /* the next open shows the truth */ }
    getJSON<{ threads: Thread[] }>(threadsUrl(q)).then((d) => setList(d.threads)).catch(() => {});
  }
  return { list, q, setQ, pin };
}

type ThreadList = ReturnType<typeof useThreadList>;

/** Every conversation: a title row (with `actions` at its end), search, pinned first, then by day. Tap to open one;
 *  the star pins it. Drawn inside the sheet on a phone and in the sidebar on a desktop. `pickThread` is the picked
 *  personality's current thread (its history says which), the one its "Current chat" row opens. */
function ThreadsPanel({ threads, current, pickThread, onOpen, actions }: { threads: ThreadList; current: string | null; pickThread: string | null; onOpen: (t: Thread | null) => void; actions: ReactNode }) {
  const { list, q, setQ, pin } = threads;
  const pick = usePick();
  const firstRow = pick ? "Current chat" : "Today's chat";  // a personality's chat doesn't start fresh each day
  const today = todayISO();
  // The top row already opens one chat: the list below doesn't show it again (a search shows everything).
  let listed = list ?? [];
  if (!q) {
    const shownAbove = sameAsTopRow(listed, today, pick, pickThread);
    listed = listed.filter((t) => t.id !== shownAbove);
  }
  const groups = groupThreads(listed, today);
  return (
    <>
      <div className="px-4 pb-3 flex items-center gap-2">
        <div className="text-[21px] font-bold tracking-[-0.015em] flex-1">Threads</div>
        {actions}
      </div>
      <div className="px-4 pb-2">
        <div className="flex items-center gap-2 h-11 px-3.5 rounded-full bg-well border border-line">
          <span className="text-muted"><Icon name="search" size={16} /></span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your chats" type="search" autoCorrect="off"
            className="flex-1 min-w-0 bg-transparent outline-none text-[15px]" />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto no-scrollbar px-2 pb-8">
        {!q && (
          <button onClick={() => onOpen(null)} className={`w-full flex items-center gap-3 px-3 py-3 rounded-[16px] text-left ${current === null ? "bg-well" : ""}`}>
            <span className="w-9 h-9 rounded-[12px] grid place-items-center bg-ember-tint text-ember-text"><Icon name="chat" size={16} /></span>
            <span className="flex-1"><b className="text-[15px] font-semibold block">{firstRow}</b><span className="text-[12.5px] text-muted">Where new messages go</span></span>
          </button>
        )}
        {list === null && <div className="px-3 py-4 text-[14px] text-muted">Loading…</div>}
        {list !== null && listed.length === 0 && <div className="px-3 py-4 text-[14px] text-muted">{q ? "Nothing matches." : "No earlier chats yet."}</div>}
        {groups.map((g) => (
          <div key={g.label} className="mt-3">
            <div className="px-3 pb-1 text-[13px] leading-5 font-bold text-muted">{g.label}</div>
            {g.items.map((t) => (
              <div key={t.id} className={`flex items-center gap-1 rounded-[16px] ${current === t.id ? "bg-well" : ""}`}>
                <button onClick={() => onOpen(t)} className="flex-1 min-w-0 text-left px-3 py-2.5">
                  <span className="block text-[15px] font-medium truncate">{t.title}</span>
                  <span className="block text-[12.5px] text-muted truncate">{t.snippet ?? `${whenText(t, today)} · ${t.messages} messages`}</span>
                </button>
                <button onClick={() => void pin(t)} aria-label={t.pinned ? "Unpin" : "Pin"} className={`w-10 h-10 grid place-items-center shrink-0 ${t.pinned ? "text-gold" : "text-dim"}`}>
                  <Star on={t.pinned} />
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}

/** Threads on a phone and a tablet: a sheet that slides in from the left over the chat. */
export function ThreadsSheet({ open, current, pickThread, onClose, onOpen }: {
  open: boolean; current: string | null; pickThread: string | null; onClose: () => void; onOpen: (t: Thread | null) => void;
}) {
  const threads = useThreadList(open, 0);
  // The drawer belongs to the chat, which stays mounted under other screens: a change of screen (the hash: a tab, a
  // link, #settings typed in) closes it, so it never stays open over Settings or Today. One listener for as long as
  // it is open, calling the newest onClose: App redraws the chat on the same hash change before this listener runs,
  // and a listener swapped during that redraw would be skipped by the browser for that event.
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });  // after every redraw: the newest onClose
  useEffect(() => {
    if (!open) return;
    const close = () => closeRef.current();
    window.addEventListener("hashchange", close);
    return () => window.removeEventListener("hashchange", close);
  }, [open]);
  return (
    <ToBody>
      <AnimatePresence>
        {open && (
          <>
            <motion.div key="scrim" className="fixed inset-0 z-40 bg-black/30" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
            <motion.aside key="sheet" role="dialog" aria-label="Threads"
              className="fixed z-50 left-0 top-0 bottom-0 w-[86%] max-w-[400px] bg-ground border-r border-line shadow-2xl flex flex-col safe-top"
              initial={{ x: "-100%" }} animate={{ x: 0 }} exit={{ x: "-100%" }} transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}>
              <ThreadsPanel threads={threads} current={current} pickThread={pickThread} onOpen={onOpen}
                actions={<button onClick={onClose} aria-label="Close" className="pill w-10 h-10 px-0"><Icon name="x" size={16} /></button>} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </ToBody>
  );
}

/** Threads on a desktop: a column on the chat's left, open unless this device hid it (threadsSidebar.ts). Hidden, it
 *  folds to no width (styles.css .threads-sidebar) but stays mounted, so the fold animates and the search is kept.
 *  `reload` changes after each reply and new chat; a hidden list waits and loads when it opens again. */
export function ThreadsSidebar({ open, onHide, hideRef, current, pickThread, onOpen, onNewChat, reload }: {
  open: boolean; onHide: () => void; hideRef?: Ref<HTMLButtonElement>;
  current: string | null; pickThread: string | null; onOpen: (t: Thread | null) => void; onNewChat: () => void; reload: number;
}) {
  const threads = useThreadList(open, reload);
  const hideTitle = `Hide threads (${shortcutText(onApple())})`;
  const actions = (
    <>
      <button onClick={onNewChat} className="pill pill-flat h-10 text-[13.5px]"><Icon name="plus" size={16} /> New chat</button>
      <button ref={hideRef} onClick={onHide} aria-label="Hide threads" title={hideTitle}
        className="w-9 h-9 -mr-1.5 grid place-items-center rounded-full text-muted hover:text-ink hover:bg-well">
        <Icon name="sidebar" size={18} />
      </button>
    </>
  );
  // inert: while hidden its rows and buttons can't be tabbed to or read out.
  return (
    <div className="threads-sidebar shrink-0 h-full" data-open={open} inert={!open}>
      <aside aria-label="Threads" className="w-[300px] h-full flex flex-col safe-top border-r border-line bg-overlay backdrop-blur-xl">
        <ThreadsPanel threads={threads} current={current} pickThread={pickThread} onOpen={onOpen} actions={actions} />
      </aside>
    </div>
  );
}

/** The chat header's Threads pill. Below 1024px it opens the sheet, as it always has; on a desktop it shows only while
 *  the sidebar is hidden, and brings it back (showsThreadsPill). */
export function ThreadsPill({ wide, sidebarOpen, onPress, pillRef }: { wide: boolean; sidebarOpen: boolean; onPress: () => void; pillRef?: Ref<HTMLButtonElement> }) {
  if (!showsThreadsPill(wide, sidebarOpen)) return null;
  let label = "Threads";
  let title = "Threads";
  if (wide) {
    label = "Show threads";
    title = `Show threads (${shortcutText(onApple())})`;
  }
  return <button ref={pillRef} onClick={onPress} aria-label={label} title={title} className="pill w-11 px-0"><Icon name="menu" size={18} /></button>;
}

export { Star };
