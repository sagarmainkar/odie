export type NewsItem = { title: string; link: string; source: string; topic: string; published: string | null; image: string | null };
export type NewsBatch = { fetched_at: string | null; topics: string[]; items: NewsItem[] };

/** "45 min ago", "3h ago", "yesterday"; "" when there's no usable time. */
export function ago(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const min = Math.max(0, Math.floor((now.getTime() - t) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function askAbout(item: NewsItem): string {
  return `Tell me more about this story: ${item.title} (${item.link})`;
}
