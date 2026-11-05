import type { Approval } from "./components/ApprovalCard";

/** The card after a live answer: its new status, and the moment we heard it if the server gave no time. A status
 * of "pending" or none at all changes nothing.
 *    pending card, status "approved"  -> approved, decided_at = now
 *    approved card with decided_at    -> unchanged (the server's time stands)
 *    any card, status undefined       -> unchanged */
export function answered(a: Approval, status: string | undefined): Approval {
  if (!status || status === "pending") return a;
  return { ...a, status, decided_at: a.decided_at ?? new Date().toISOString() };
}
