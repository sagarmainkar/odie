/** Think harder, as Odie keeps it for each chat (GET/PUT /api/chat/thinking), so every app shows the same choice. */
import { getJSON, putJSON } from "./api";

export type ChatThinking = { session_id: string; on: boolean };

/** The chat's setting; no session id: today's current chat (the server says which one that is). */
export function loadThinking(sessionId?: string): Promise<ChatThinking> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return getJSON<ChatThinking>(`/api/chat/thinking${query}`);
}

/** Turn it on or off for this chat; new chats start with it too, and every open app hears of it. */
export function saveThinking(on: boolean, sessionId?: string): Promise<ChatThinking> {
  const body = sessionId ? { session_id: sessionId, on } : { on };
  return putJSON<ChatThinking>("/api/chat/thinking", body);
}

/**
 * What the chat on screen shows after a live event: the event's value when it's about that chat, else what it showed.
 *   showing chat-2026-10-28 off, {thinking chat-2026-10-28 on}   -> on
 *   showing chat-2026-10-28 off, {thinking chat-2026-10-27 on}   -> off (another chat changed)
 *   showing nothing yet,         {thinking chat-2026-10-28 on}   -> nothing yet (the GET answers for this chat)
 *   showing chat-2026-10-28 off, {message …}                     -> off
 */
export function thinkingAfter(shown: ChatThinking | null, e: { type: string; session_id?: string; on?: boolean }): ChatThinking | null {
  if (e.type !== "thinking" || shown === null) return shown;
  if (e.session_id !== shown.session_id) return shown;
  return { session_id: shown.session_id, on: !!e.on };
}
