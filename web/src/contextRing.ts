/** Whether the header shows how full the conversation is: only once it is half full, so a fresh chat's header is calm.
 *    2K of 32K used   -> false, nothing in the header
 *    16K of 32K used  -> true, the ring shows 50%
 *    a limit of 0 (not known yet) -> false */
export function ctxWorthShowing(used: number, limit: number): boolean {
  if (limit <= 0) return false;
  return used / limit >= 0.5;
}
