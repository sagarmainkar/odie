// Each personality has a light of its own: the wash behind every screen, its face and its picture's ring take one of
// six palettes (styles.css, data-light), so who you are talking to is felt before it is read. Everyday Odie has
// none and keeps the wash that follows the time of day.
export const LIGHTS = ["sage", "rose", "ocean", "amber", "violet", "slate"] as const;

/** Which light a personality has.
 *    ""  (everyday Odie)  -> 0, no light of its own
 *    "980a3305d04e"       -> a number from 1 to 6, the same one every time for that id */
export function lightOf(id: string): number {
  if (!id) return 0;
  let mixed = 2166136261;  // FNV-1a: ids that differ by one letter still land on different lights
  for (let i = 0; i < id.length; i += 1) {
    mixed ^= id.charCodeAt(i);
    mixed = Math.imul(mixed, 16777619) >>> 0;
  }
  mixed = (mixed ^ (mixed >>> 15)) >>> 0;  // fold the high bits in: the low ones alone repeat
  return (mixed % LIGHTS.length) + 1;
}

/** Turn the whole app's wash to the picked one's light (or back to the time of day for Odie). */
export function applyLight(pick: string): void {
  const light = lightOf(pick);
  if (light === 0) delete document.documentElement.dataset.light;
  else document.documentElement.dataset.light = String(light);
}
