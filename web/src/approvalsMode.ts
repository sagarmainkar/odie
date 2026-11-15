/** The approvals mode, Careful or Smart: one setting for the whole app (GET/PUT /api/approvals/mode), read once and
 * shared by Settings and every approval card, so a change in Settings reaches the cards without a reload. */
import { useEffect, useState } from "react";
import { getJSON, putJSON } from "./api";

export type ApprovalsMode = "careful" | "smart";

/** What Settings says under each choice. */
export const MODE_COPY: Record<ApprovalsMode, { title: string; line: string }> = {
  careful: { title: "Careful", line: "Every command and every change asks first; a 30-minute pass is offered on each shell card." },
  smart: {
    title: "Smart",
    line: "Commands, reads and plain writes run on their own and show in each reply's steps. Installing, deleting outside Odie's folders, sending, paying or ordering, and reading secrets always ask.",
  },
};

/** The mode a server answer names; anything that isn't "smart" is Careful (the safe reading of an odd value):
 *    "smart" -> "smart";  "careful" -> "careful";  undefined or "yolo" -> "careful" */
export function asMode(value: unknown): ApprovalsMode {
  return value === "smart" ? "smart" : "careful";
}

let known: ApprovalsMode | null = null;
let fetching: Promise<ApprovalsMode> | null = null;
const listeners = new Set<(m: ApprovalsMode) => void>();

/** The mode, fetched once per page load and remembered; concurrent readers share one request. */
export async function readMode(): Promise<ApprovalsMode> {
  if (known) return known;
  if (!fetching) {
    fetching = getJSON<{ mode?: string }>("/api/approvals/mode")
      .then((r) => { known = asMode(r?.mode); return known; })
      .finally(() => { fetching = null; });
  }
  return fetching;
}

/** Save the mode and tell every open card and the Settings row. */
export async function setMode(mode: ApprovalsMode): Promise<void> {
  await putJSON("/api/approvals/mode", { mode });
  known = mode;
  listeners.forEach((f) => f(mode));
}

/** Forget what was read (tests, and a sign-out). */
export function forgetMode(): void {
  known = null;
}

/** Read the mode again (the page came back into view: it may have been switched on another device) and tell
 * everyone when it changed. */
export async function refreshMode(): Promise<void> {
  known = null;
  const mode = await readMode();
  listeners.forEach((f) => f(mode));
}

/** The live mode for a component: null until it is known, then every change made through setMode. */
export function useApprovalsMode(): ApprovalsMode | null {
  const [mode, setLocal] = useState<ApprovalsMode | null>(known);
  useEffect(() => {
    let mounted = true;
    const follow = (m: ApprovalsMode) => { if (mounted) setLocal(m); };
    listeners.add(follow);
    readMode().then(follow).catch(() => {});  // unreachable server: the card keeps its Careful look
    const onShow = () => { if (document.visibilityState === "visible") void refreshMode().catch(() => {}); };
    document.addEventListener("visibilitychange", onShow);
    return () => { mounted = false; listeners.delete(follow); document.removeEventListener("visibilitychange", onShow); };
  }, []);
  return mode;
}
