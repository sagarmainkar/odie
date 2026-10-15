import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "../api";
import { memoToPlay, withNotice, withoutNotice, type Notice } from "../curtain";
import { useLive } from "../live";
import { mediaUrl } from "../media";
import { usePersona } from "../persona";
import { somethingPlaying } from "../playing";
import { Avatar } from "./Avatar";

/** The event Chat listens for after Act: put the cursor in the composer, ready to type. */
export const FOCUS_COMPOSER = "odie:focus-composer";

/**
 * A reminder that fired comes down over whatever's on screen, like a curtain from the top: Odie's face, the words,
 * and two choices. Dismiss closes it (the reminder stays on Today under Now). Act puts it into the chat as Odie's
 * message, opens the chat and puts the cursor in the composer, so the reply is one tap away. Several waiting
 * reminders show one at a time, oldest first; a spoken one plays as the curtain opens.
 */
export function ReminderCurtain() {
  const [queue, setQueue] = useState<Notice[]>([]);
  const persona = usePersona();
  const played = useRef<Set<number>>(new Set());

  // Waiting notices when the app opens or comes back, and new ones as they fire.
  const refresh = useCallback(() => {
    getJSON<Notice[]>("/api/reminders/pending").then((list) => setQueue((q) => list.reduce(withNotice, q))).catch(() => {});
  }, []);
  useEffect(refresh, [refresh]);
  useLive(useCallback((e: any) => {
    if (e.type === "reminder") setQueue((q) => withNotice(q, { id: e.id, text: e.text, kind: e.kind ?? "reminder", ts: e.ts, media: e.media }));
  }, []), refresh);

  const current = queue[0];
  useEffect(() => {
    if (!current || played.current.has(current.id)) return;
    const memo = memoToPlay(current, document.visibilityState === "visible", somethingPlaying());
    if (!memo) return;
    played.current.add(current.id);
    void new Audio(mediaUrl({ id: memo })).play().catch(() => {});
  }, [current]);

  async function dismiss(n: Notice) {
    setQueue((q) => withoutNotice(q, n.id));
    await postJSON(`/api/reminders/${n.id}/dismiss`, {}).catch(() => {});
  }

  async function act(n: Notice) {
    setQueue((q) => withoutNotice(q, n.id));
    await postJSON(`/api/reminders/${n.id}/act`, {}).catch(() => {});
    location.hash = "#chat";
    setTimeout(() => window.dispatchEvent(new Event(FOCUS_COMPOSER)), 80);
  }

  return (
    <AnimatePresence>
      {current && (
        <motion.div key={current.id} role="dialog" aria-label="Reminder" initial={{ y: -140, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -140, opacity: 0 }}
          transition={{ type: "spring", stiffness: 260, damping: 26 }} className="fixed top-0 left-0 right-0 z-40 flex justify-center px-3 pt-[max(12px,env(safe-area-inset-top))] pointer-events-none">
          <div className="glass glass-solid rounded-[26px] px-4 py-3.5 w-full max-w-[560px] shadow-[0_24px_60px_-24px_rgba(60,40,20,.45)] pointer-events-auto">
            <div className="flex items-start gap-3">
              <Avatar size={40} state="approval" />
              <div className="flex-1 min-w-0">
                <div className="text-[12.5px] font-semibold text-muted">{persona.name} · reminder</div>
                <div className="text-[15.5px] leading-[21px] font-semibold mt-0.5 break-words">{current.text}</div>
                {queue.length > 1 && <div className="text-[12px] text-dim mt-1">{queue.length - 1} more waiting</div>}
              </div>
            </div>
            <div className="flex gap-2 mt-3">
              <button type="button" onClick={() => void dismiss(current)} className="pill flex-1 h-11 text-[15px] shadow-none">Dismiss</button>
              <button type="button" onClick={() => void act(current)} className="pill pill-solid flex-1 h-11 text-[15px] shadow-none">Act</button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
