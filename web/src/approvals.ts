import type { Approval, ChatPass } from "./components/ApprovalCard";

/** The card after a live answer: its new status, and the moment we heard it if the server gave no time. A shell pass
 * the tap granted (allowedUntil) and a "don't ask again in this chat" pass (chatPass) are kept on the card for its
 * stamp. A status of "pending" or none at all changes nothing.
 *    pending card, status "approved"  -> approved, decided_at = now
 *    pending card, "approved" + pass until 12:31 -> approved, allowed_until = 12:31
 *    pending card, "approved" + chat pass for deletes until 12:31 -> approved, chat_pass = that pass
 *    approved card with decided_at    -> unchanged (the server's time stands)
 *    any card, status undefined       -> unchanged */
export function answered(a: Approval, status: string | undefined, allowedUntil?: string, chatPass?: ChatPass): Approval {
  if (!status || status === "pending") return a;
  return {
    ...a, status, decided_at: a.decided_at ?? new Date().toISOString(), allowed_until: allowedUntil ?? a.allowed_until,
    chat_pass: chatPass ?? a.chat_pass,
  };
}
