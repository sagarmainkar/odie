// Asking Odie for today's morning hello, for the card above the chat (components/MorningCard.tsx).
import { useEffect, useState } from "react";
import { getJSON, todayISO } from "./api";
import { isDayStartChat, keepAsking, MORNING_ASK_EVERY_MS, type MorningReply, type MorningState } from "./morning";

/** Today's hello from GET /api/morning, for the chat on screen. Asked when today's chat opens (and again when the app
 * comes back on screen, so a phone left open overnight gets the new day's); while the hello is being made it asks every
 * 10 s, for up to 3 minutes, then gives up and draws nothing. A later segment or an old thread never asks.
 * null: nothing to draw. */
export function useMorning(threadId: string | null): MorningReply | null {
  const [reply, setReply] = useState<MorningReply | null>(null);
  const [wake, setWake] = useState(0);
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") setWake((n) => n + 1); };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  const dayStart = isDayStartChat(threadId, todayISO());
  useEffect(() => {
    if (!dayStart) return;
    let closed = false;  // the chat changed or closed: answers still on their way are dropped
    let timer: number | undefined;
    let last: MorningState = "none";
    const startedAt = Date.now();
    const ask = async () => {
      try {
        const got = await getJSON<MorningReply>("/api/morning");
        if (closed) return;
        last = got.state;
        setReply(got);
      } catch { /* offline: ask again on the next round if it was being made */ }
      if (closed) return;
      if (keepAsking(last, startedAt, Date.now())) {
        timer = window.setTimeout(() => void ask(), MORNING_ASK_EVERY_MS);
        return;
      }
      if (last === "making") setReply(null);  // three minutes and still not ready: draw nothing
    };
    void ask();
    return () => { closed = true; window.clearTimeout(timer); };
  }, [threadId, dayStart, wake]);

  if (!dayStart) return null;
  return reply;
}
