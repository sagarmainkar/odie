/** What a tool made for the chat (odie/media.py): a voice memo, a podcast, a screenshot or a file, drawn under the
 * reply. It arrives as a live "media" event while the turn runs, and with the reply in history after a reload. */
import type { Deck } from "./deck";

export type Turn = { host: string; text: string; start: number };
export type Media = {
  id: string; kind: "memo" | "podcast" | "screenshot" | "file" | "page" | "link" | "turn" | "tracker" | "picture" | "video" | "audio"; title: string; mime: string; size: number; created: number;
  duration?: number; peaks?: number[]; transcript?: string | Turn[]; voice?: string; hosts?: { name: string; group: string; voice?: string }[];
  url?: string; page_title?: string; step?: string;  // a screenshot: the page and the browser step that took it
  filename?: string;  // a file: its name for the download
  deck?: Deck;  // a designed deck (odie/decks): its PowerPoint and slide pictures
  site?: string; tab?: string; why?: string;  // a "your turn" card (signed-in browsing): the site, the browser tab, why
  state?: "done" | "code" | "failed" | "captcha" | "vault"; auto?: boolean;  // a "your turn" card: where the sign-in stands
  label?: string;  // a link: its button (a UPI app link's "Pay in your UPI app")
  tracker_id?: number; page?: string;  // a "check this page signed in?" card (odie/trackers/signed_in.py)
  format?: "story";  // a podcast that is an audio story (a user skill can make one): its hosts are the cast
};

export const mediaUrl = (m: Pick<Media, "id">) => `/api/media/${m.id}`;

export function clock(seconds: number): string {
  const t = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

/** Which waveform bars are played, at `progress` (0 to 1). */
export function filled(peaks: number[], progress: number): boolean[] {
  return peaks.map((_, i) => (i + 0.5) / peaks.length <= progress);
}

/** The podcast turn playing at `t` seconds (-1 before it starts, or for a memo). */
export function turnAt(m: Media, t: number): number {
  const turns = Array.isArray(m.transcript) ? m.transcript : [];
  let at = -1;
  turns.forEach((x, i) => { if (x.start <= t + 0.05) at = i; });
  return at;
}

/** Which host (index into hosts) is speaking at `t`. */
export function speakingAt(m: Media, t: number): number {
  const i = turnAt(m, t);
  const turns = Array.isArray(m.transcript) ? m.transcript : [];
  return i < 0 ? -1 : (m.hosts ?? []).findIndex((h) => h.name === turns[i].host);
}

/**
 * The letter on a host's avatar: the first letter of the label's last word, so the podcast skill's neutral labels
 * still differ. "Host A" → "A", "Host B" → "B", "Asha" → "A".
 */
export function hostInitial(name: string): string {
  const words = name.trim().split(/\s+/);
  return (words[words.length - 1] ?? "").slice(0, 1).toUpperCase();
}

const LEADING_ARTICLES = new Set(["the", "a", "an"]);

/** A story speaker's two-letter mark: the initials of the first two words, a leading "The" left out, or the first two
 *  letters of a one-word name. "Captain Silas Blackwater" → "CS"; "The keeper" → "Ke"; "Narrator" → "Na". */
function twoLetters(name: string): string {
  let kept = name.trim().split(/\s+/).filter(Boolean);
  const startsWithArticle = kept.length > 1 && LEADING_ARTICLES.has(kept[0].toLowerCase());
  if (startsWithArticle) kept = kept.slice(1);
  if (kept.length >= 2) return (kept[0][0] + kept[1][0]).toUpperCase();
  const word = kept[0] ?? "";
  return word.slice(0, 1).toUpperCase() + word.slice(1, 2).toLowerCase();
}

/**
 * Decides the mark on each speaker's avatar. A podcast keeps hostInitial's one letter ("Host A" → "A"). An audio
 * story's cast is bigger and often shares a first letter, so each gets two (twoLetters), and a mark already taken
 * becomes its first letter and a number. ["Narrator", "Nell", "The keeper"] → ["Na", "Ne", "Ke"]; ["Nell", "Nelson"]
 * → ["Ne", "N2"].
 */
export function castMarks(m: Media, names: string[]): string[] {
  if (!isStory(m)) return names.map(hostInitial);
  const marks: string[] = [];
  names.forEach((name, i) => {
    let mark = twoLetters(name);
    if (marks.includes(mark)) mark = `${mark.slice(0, 1)}${i + 1}`;
    marks.push(mark);
  });
  return marks;
}

/** The two hosts' colours: solid tokens (a gradient is dropped from rings and text). */
export const HOST_TONES = ["var(--t-brand)", "var(--t-host-b)"];
export const HOST_TEXT = ["var(--t-brand-text)", "var(--t-host-b-text)"];

/** An audio story's speakers' colours: the podcast's two, then six more, cycling after eight. */
export const CAST_TONES = [...HOST_TONES, ...[3, 4, 5, 6, 7, 8].map((n) => `var(--t-cast-${n})`)];
export const CAST_TEXT = [...HOST_TEXT, ...[3, 4, 5, 6, 7, 8].map((n) => `var(--t-cast-${n}-text)`)];

/** How the line under the title is drawn: a story's cast wraps, so every voice is shown; a podcast's two hosts stay on
 *  one line. */
export function castLineLook(m: Media): string {
  if (isStory(m)) return "leading-4 mt-0.5";
  return "truncate";
}

/** Whether a podcast player is an audio story: { format: "story" } → true; a podcast → false. */
export function isStory(m: Media): boolean {
  return m.format === "story";
}

/** The colour of the speaker at index `i`: a story's cycle through eight (index 8 → the first again); a podcast's
 * through its two hosts (index 2 → the first). */
export function toneAt(m: Media, i: number): string {
  if (isStory(m)) return CAST_TONES[i % CAST_TONES.length];
  return HOST_TONES[i % HOST_TONES.length];
}

/** The same, for a speaker's name in the transcript. */
export function textToneAt(m: Media, i: number): string {
  if (isStory(m)) return CAST_TEXT[i % CAST_TEXT.length];
  return HOST_TEXT[i % HOST_TEXT.length];
}

/** The player's words: a story → "Audio story", "Play story"; a podcast → "Podcast", "Play podcast". */
export function playerWords(m: Media): { label: string; play: string; pause: string; position: string } {
  if (isStory(m)) return { label: "Audio story", play: "Play story", pause: "Pause story", position: "Story position" };
  return { label: "Podcast", play: "Play podcast", pause: "Pause podcast", position: "Podcast position" };
}

/** Who is in it, under the title: a story's cast with their voices ("Narrator · Heart, The keeper · Michael"); a
 * podcast's two hosts ("Host A and Host B"). */
export function castLine(m: Media): string {
  const hosts = m.hosts ?? [];
  if (!isStory(m)) return hosts.map((h) => h.name).join(" and ");
  const named = hosts.map((h) => (h.voice ? `${h.name} · ${h.voice}` : h.name));
  return named.join(", ");
}

/** The messages with `m` on the reply being written (`at`; else the last reply), unless it's already there. A reminder
 * can arrive while a reply is written, so Chat names the reply. */
export function withMedia<T extends { role: string; media?: Media[] }>(msgs: T[], m: Media, at?: (x: T) => boolean): T[] {
  const i = at ? msgs.findIndex(at) : msgs.map((x) => x.role).lastIndexOf("odie");
  if (i < 0 || msgs[i].media?.some((x) => x.id === m.id)) return msgs;
  const out = [...msgs];
  out[i] = { ...msgs[i], media: [...(msgs[i].media ?? []), m] };
  return out;
}
