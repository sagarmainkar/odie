// Saving what the user did to a block in a reply (a checklist's ticks) on the server, so it survives a reload and
// shows on the laptop too. A reply is named by its chat session and its key (the ADK event id its text came from,
// which is the same while it streams in and after any reload); a block by "<fence>/<place in the fence>": "0/2" is the
// third block of the reply's first fence, "1/0.children.1" the second child of the first block of its second fence.
import { getJSON } from "../api";

export type Reply = { sessionId: string; messageKey: string };

const SAVE_AFTER_MS = 400;

// Values waiting to be sent, one per reply and block: a quick run of taps sends only the last value.
type Waiting = { reply: Reply; path: string; value: unknown; timer: ReturnType<typeof setTimeout> };
const waiting = new Map<string, Waiting>();

function slot(reply: Reply, path: string): string {
  return `${reply.sessionId} ${reply.messageKey} ${path}`;
}

function sameReply(a: Reply, b: Reply): boolean {
  return a.sessionId === b.sessionId && a.messageKey === b.messageKey;
}

/** Every saved value in one reply, by block path: {"0/2": [0, 3]}. A value still waiting to be sent wins over the
 *  server's (it is newer): the history reloading a moment after a tap must not bring the old ticks back. */
export async function loadReply(reply: Reply): Promise<Record<string, unknown>> {
  const query = `session_id=${encodeURIComponent(reply.sessionId)}&message_key=${encodeURIComponent(reply.messageKey)}`;
  const got = await getJSON<{ values: Record<string, unknown> }>(`/api/block-state?${query}`);
  const values: Record<string, unknown> = { ...got.values };
  for (const w of waiting.values()) {
    if (sameReply(w.reply, reply)) values[w.path] = w.value;
  }
  return values;
}

/** Saves a block's value a moment from now; another value for the same block before then replaces it. */
export function saveSoon(reply: Reply, path: string, value: unknown, delayMs = SAVE_AFTER_MS): void {
  const key = slot(reply, path);
  const before = waiting.get(key);
  if (before) clearTimeout(before.timer);
  const timer = setTimeout(() => {
    waiting.delete(key);
    void send(reply, path, value);
  }, delayMs);
  waiting.set(key, { reply, path, value, timer });
}

/** Sends everything still waiting, now (the app is going to the background, where a timer may never fire). */
export function saveWaitingNow(): void {
  for (const [key, w] of waiting) {
    clearTimeout(w.timer);
    waiting.delete(key);
    void send(w.reply, w.path, w.value);
  }
}

async function send(reply: Reply, path: string, value: unknown): Promise<void> {
  const body = { session_id: reply.sessionId, message_key: reply.messageKey, block_path: path, value };
  try {
    await fetch("/api/block-state", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), keepalive: true });
  } catch {
    // Offline: the tick stays on screen, and the next tap sends the whole list again.
  }
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveWaitingNow();
  });
}

// --- Checklist ticks: the list of ticked item numbers, [0, 3] ------------------------------------------------------

/** Ticks after a tap on item `i`: an unticked item is ticked, a ticked one unticked; kept in order.
 *  [0, 3] tap 2 → [0, 2, 3];  [0, 3] tap 3 → [0] */
export function toggleTick(ticks: number[], i: number): number[] {
  if (ticks.includes(i)) return ticks.filter((t) => t !== i);
  return [...ticks, i].sort((a, b) => a - b);
}

/** What was saved for a checklist of `count` items, as ticks it can show; null when nothing usable was saved.
 *  [3, 0, 3] with 5 items → [0, 3];  [0, 9] with 5 items → [0] (item 9 isn't there);  "yes" → null;  undefined → null */
export function readTicks(saved: unknown, count: number): number[] | null {
  if (!Array.isArray(saved)) return null;
  const ticks = new Set<number>();
  for (const t of saved) {
    const isItem = Number.isInteger(t) && t >= 0 && t < count;
    if (isItem) ticks.add(t);
  }
  return [...ticks].sort((a, b) => a - b);
}

/**
 * What a checklist shows once its reply's saved values arrive, and whether to save what it shows:
 * - no tap yet: the saved ticks, or the model's starting ticks when nothing is saved
 *   (saved [1, 2] → show [1, 2]; nothing saved, model said [0] → show [0]; nothing to save either way)
 * - the user tapped before they arrived (a slow connection): keep the taps, and save them, since they're newer
 *   (saved [1], tapped to [0, 1, 4] meanwhile → show [0, 1, 4], save)
 */
export function ticksAfterLoad(saved: number[] | null, onScreen: number[], tapped: boolean): { show: number[]; save: boolean } {
  if (tapped) return { show: onScreen, save: true };
  if (saved) return { show: saved, save: false };
  return { show: onScreen, save: false };
}
