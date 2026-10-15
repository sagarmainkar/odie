import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState, type ReactNode } from "react";
import { getJSON, postJSON, todayISO } from "../api";
import { groupThreads, whenText, type Thread } from "../threads";
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
  useEffect(() => {
    if (!active) return;
    const id = setTimeout(() => {
      getJSON<{ threads: Thread[] }>(threadsUrl(q)).then((d) => setList(d.threads)).catch(() => setList([]));
    }, q ? 250 : 0);
    return () => clearTimeout(id);
  }, [active, q, reload]);

  async function pin(t: Thread) {
    setList((l) => l?.map((x) => (x.id === t.id ? { ...x, pinned: !t.pinned } : x)) ?? l);
    try { await postJSON(`/api/threads/${t.id}/pin`, { pinned: !t.pinned }); } catch { /* the next open shows the truth */ }
    getJSON<{ threads: Thread[] }>(threadsUrl(q)).then((d) => setList(d.threads)).catch(() => {});
  }
  return { list, q, setQ, pin };
}

type ThreadList = ReturnType<typeof useThreadList>;

/** Every conversation: a title row (with `actions` at its end), search, pinned first, then by day. Tap to open one;
 *  the star pins it. Drawn inside the sheet on a phone and in the sidebar on a desktop. */
function ThreadsPanel({ threads, current, onOpen, actions }: { threads: ThreadList; current: string | null; onOpen: (t: Thread | null) => void; actions: ReactNode }) {
  const { list, q, setQ, pin } = threads;
  const today = todayISO();
  const groups = list ? groupThreads(list, today) : [];
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
            <span className="flex-1"><b className="text-[15px] font-semibold block">Today's chat</b><span className="text-[12.5px] text-muted">Where new messages go</span></span>
          </button>
        )}
        {list === null && <div className="px-3 py-4 text-[14px] text-muted">Loading…</div>}
        {list?.length === 0 && <div className="px-3 py-4 text-[14px] text-muted">{q ? "Nothing matches." : "No earlier chats yet."}</div>}
        {groups.map((g) => (
          <div key={g.label} className="mt-3">
            <div className="px-3 pb-1 text-[12px] font-bold text-muted uppercase tracking-[.05em]">{g.label}</div>
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
export function ThreadsSheet({ open, current, onClose, onOpen }: {
  open: boolean; current: string | null; onClose: () => void; onOpen: (t: Thread | null) => void;
}) {
  const threads = useThreadList(open, 0);
  return (
    <ToBody>
      <AnimatePresence>
        {open && (
          <>
            <motion.div key="scrim" className="fixed inset-0 z-40 bg-black/30" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
            <motion.aside key="sheet" role="dialog" aria-label="Threads"
              className="fixed z-50 left-0 top-0 bottom-0 w-[86%] max-w-[400px] bg-ground border-r border-line shadow-2xl flex flex-col safe-top"
              initial={{ x: "-100%" }} animate={{ x: 0 }} exit={{ x: "-100%" }} transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}>
              <ThreadsPanel threads={threads} current={current} onOpen={onOpen}
                actions={<button onClick={onClose} aria-label="Close" className="pill w-10 h-10 px-0"><Icon name="x" size={16} /></button>} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </ToBody>
  );
}

/** Threads on a desktop: always open, a column on the chat's left. `reload` changes after each reply and new chat. */
export function ThreadsSidebar({ current, onOpen, onNewChat, reload }: {
  current: string | null; onOpen: (t: Thread | null) => void; onNewChat: () => void; reload: number;
}) {
  const threads = useThreadList(true, reload);
  return (
    <aside aria-label="Threads" className="shrink-0 w-[300px] h-full flex flex-col safe-top border-r border-line bg-overlay backdrop-blur-xl">
      <ThreadsPanel threads={threads} current={current} onOpen={onOpen}
        actions={<button onClick={onNewChat} className="pill pill-flat h-10 text-[13.5px]"><Icon name="plus" size={16} /> New chat</button>} />
    </aside>
  );
}

export { Star };
