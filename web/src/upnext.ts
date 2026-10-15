import { userLocale } from "./locale";
export type UpItem = {
  id: string; source: "calendar" | "sms" | "mail" | "task"; sources: string[]; kind: string; title: string;
  date: string; time: string | null; end: string | null; place: string | null; people: string[] | null; amount: number | null; ask: string;
};

const SOURCE_LABEL: Record<string, string> = { calendar: "Calendar", sms: "SMS", mail: "Mail", task: "Task" };
export const sourceText = (it: UpItem) => it.sources.map((s) => SOURCE_LABEL[s] ?? s).join(" · ");

/** "In 25 min", "In 3 h", "Tomorrow", "In 3 days", "In 2 weeks" */
export function relative(it: UpItem, now = new Date()): string {
  const today = now.toLocaleDateString("en-CA");
  const days = Math.round((Date.parse(it.date) - Date.parse(today)) / 86400000);
  if (days === 0) {
    if (!it.time) return "Today";
    const [h, m] = it.time.split(":").map(Number);
    const mins = h * 60 + m - (now.getHours() * 60 + now.getMinutes());
    return mins <= 0 ? "Now" : mins < 60 ? `In ${mins} min` : `In ${Math.round(mins / 60)} h`;
  }
  if (days === 1) return "Tomorrow";
  return days < 7 ? `In ${days} days` : `In ${Math.round(days / 7)} week${days >= 11 ? "s" : ""}`;  // the weekday is already on the card
}

export function dateParts(date: string): { day: number; month: string; weekday: string; short: string } {
  const d = new Date(date + "T00:00:00");
  return { day: d.getDate(), month: d.toLocaleDateString(userLocale(), { month: "long", year: "numeric" }),
           weekday: d.toLocaleDateString(userLocale(), { weekday: "long" }), short: d.toLocaleDateString(userLocale(), { weekday: "short" }) };
}

export function timeText(it: UpItem): string {
  if (it.time) return it.end ? `${it.time}–${it.end}` : it.time;
  if (it.kind === "delivery") return /· delivered$/.test(it.title) ? "Delivered" : "On the way";
  return "All day";
}

/** The line under the title: amount for dues, else the place, else who's coming. */
export function subline(it: UpItem): string {
  if (it.amount != null) return `₹${it.amount.toLocaleString("en-IN", { maximumFractionDigits: 0 })} due`;
  if (it.place) return it.place;
  if (it.people?.length) return it.people.length === 1 ? it.people[0].split("@")[0] : `${it.people.length} people`;
  return "";
}

/** Dates that have something, for the week strip's dots. */
export const busyDates = (items: UpItem[]) => new Set(items.map((i) => i.date));

/** Today's and tomorrow's items in the shape the day bands draw (time, end, title). */
export function dayEvents(items: UpItem[], date: string): { time: string; end?: string; title: string }[] {
  return items.filter((i) => i.date === date).map((i) => (i.time ? { time: i.time, end: i.end ?? undefined, title: i.title } : { time: "All day", title: i.title }));
}
