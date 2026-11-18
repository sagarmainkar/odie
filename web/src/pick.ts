import { useEffect, useState } from "react";

/** Which personality this device is talking to (odie.personalities on the server): "" is everyday Odie. It is kept in
 *  this browser, so the phone and the Mac don't follow each other. The server calls that mean something else for each
 *  personality carry it as a `personality` parameter (withPick); a call without one is for everyday Odie. */
export const PICK_KEY = "odie:personality";
const CHANGED = "odie:pick";

/** The pick made in this page, for a browser that won't keep it (private mode): it then lasts until a reload. */
let pickedHere: string | null = null;

export function getPick(): string {
  if (pickedHere !== null) return pickedHere;
  try {
    if (typeof localStorage === "undefined") return "";
    return localStorage.getItem(PICK_KEY) || "";
  } catch {
    return "";  // storage that can't be read: everyday Odie
  }
}

/** Switch to a personality ("" for everyday Odie). Every screen that follows the pick hears of it. */
export function setPick(id: string): void {
  pickedHere = id;
  try {
    if (id) localStorage.setItem(PICK_KEY, id);
    else localStorage.removeItem(PICK_KEY);
  } catch { /* not kept: it lasts until a reload */ }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGED));
}

export function onPickChange(fn: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(CHANGED, fn);
  return () => window.removeEventListener(CHANGED, fn);
}

export function usePick(): string {
  const [pick, set] = useState(getPick());
  useEffect(() => onPickChange(() => set(getPick())), []);
  return pick;
}

/** The server paths that mean something else for each personality: the chat, its history, the threads, the cards, the
 *  live stream, and its Pulse (its Needs you, its loops, its watch's card and what it closed). Everything else (tasks,
 *  the watch's count, Odie's own name and picture) is the same whoever is picked. */
const FOLLOWS = ["/api/chat", "/api/history", "/api/threads", "/api/approvals", "/api/events", "/api/needs_you", "/api/loops",
  "/api/watch/seen", "/api/watch/done", "/api/tasks/closed_by_watch"];

/** Whether a call is one of those: "/api/threads?q=x" -> true; "/api/approvals/7/decide" -> true;
 *  "/api/tasks" -> false; "/api/chats" -> false (only the path itself, or what is under it). */
export function followsPick(url: string): boolean {
  const path = url.split("?")[0];
  return FOLLOWS.some((p) => path === p || path.startsWith(p + "/"));
}

/** A call's address, naming the picked personality when the call follows the pick:
 *    ("/api/threads?q=x", "abc") -> "/api/threads?q=x&personality=abc";  ("/api/threads?q=x", "") -> unchanged;
 *    ("/api/tasks", "abc") -> unchanged.
 *  `always`: say who even for everyday Odie and on any path; the live stream and Settings' name, picture and
 *  personality boxes ask this way:  ("/api/events", "", true) -> "/api/events?personality=". */
export function withPickOf(url: string, pick: string, always = false): string {
  if (/[?&]personality=/.test(url)) return url;  // it already says who
  const says = always || (pick !== "" && followsPick(url));
  if (!says) return url;
  const joiner = url.includes("?") ? "&" : "?";
  return `${url}${joiner}personality=${encodeURIComponent(pick)}`;
}

/** A call for everyday Odie's, whoever is picked: Today and the Ask bar are Odie's screens, so their count of cards
 *  waiting is Odie's even while the chat is with a personality:  "/api/approvals" -> "/api/approvals?personality=". */
export function everyday(url: string): string {
  return withPickOf(url, "", true);
}

export function withPick(url: string, always = false): string {
  return withPickOf(url, getPick(), always);
}

/** The pick to keep once the list of personalities is known: one that was deleted (on another device, say) falls
 *  back to everyday Odie:  ("gone", ["abc"]) -> "";  ("abc", ["abc"]) -> "abc". */
export function settlePick(pick: string, known: string[]): string {
  return known.includes(pick) ? pick : "";
}
