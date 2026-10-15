/** One greeting for every screen, by the phone's local hour. The accent word is styled in serif italic. */
export function greetingParts(hour = new Date().getHours()): { lead: "Good" | "Still"; accent: "morning" | "afternoon" | "evening" | "up" } {
  if (hour < 5) return { lead: "Still", accent: "up" };
  return { lead: "Good", accent: hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening" };
}

export function greeting(hour = new Date().getHours(), name = ""): string {
  const p = greetingParts(hour);
  return `${p.lead} ${p.accent}${name ? `, ${name}` : ""}.`;
}
