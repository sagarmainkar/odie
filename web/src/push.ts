/** The notification row's line for each state of the browser's permission, in plain words.
 *    "default"                -> "Off"
 *    "denied" on an iPhone    -> "Blocked: allow notifications for Odie in the iPhone's Settings"
 *    "denied" elsewhere       -> "Blocked: allow notifications for this site in the browser's settings"
 *    "granted" (not finished) -> "Allowed: tap Enable to finish"
 *    "failed"                 -> "Couldn't turn them on. Try again."
 *    any other line we set (e.g. "Add Odie to your Home Screen…") -> as it is */
export function pushSub(push: string, apple: boolean): string {
  if (push === "default") return "Off";
  if (push === "denied" && apple) return "Blocked: allow notifications for Odie in the iPhone's Settings";
  if (push === "denied") return "Blocked: allow notifications for this site in the browser's settings";
  if (push === "granted") return "Allowed: tap Enable to finish";
  if (push === "failed") return "Couldn't turn them on. Try again.";
  return push;
}
