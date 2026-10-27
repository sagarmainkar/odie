/** What a tool made for the chat (odie/media.py): a voice memo, a podcast, a screenshot or a file, drawn under the
 * reply. It arrives as a live "media" event while the turn runs, and with the reply in history after a reload. */
import type { Deck } from "./deck";

export type Turn = { host: string; text: string; start: number };
/** A podcast host or a voice in a story. A story's `who` says who they are in a few words ("the widow who tells it"). */
export type Host = { name: string; group: string; voice?: string; who?: string };
export type Media = {
  id: string; kind: "memo" | "podcast" | "screenshot" | "file" | "page" | "link" | "turn" | "tracker" | "picture" | "video" | "audio"; title: string; mime: string; size: number; created: number;
  duration?: number; peaks?: number[]; transcript?: string | Turn[]; voice?: string; hosts?: Host[];
  url?: string; page_title?: string; step?: string;  // a screenshot: the page and the browser step that took it
  filename?: string;  // a file: its name for the download
  deck?: Deck;  // a designed deck (odie/decks): its PowerPoint and slide pictures
  site?: string; tab?: string; why?: string;  // a "your turn" card (signed-in browsing): the site, the browser tab, why
  state?: "done" | "code" | "failed" | "captcha" | "vault"; auto?: boolean;  // a "your turn" card: where the sign-in stands
  label?: string;  // a link: its button (a UPI app link's "Pay in your UPI app")
  tracker_id?: number; page?: string;  // a "check this page signed in?" card (odie/trackers/signed_in.py)
  format?: "story";  // a podcast that is an audio story (a user skill can make one): its hosts are the cast
  teaser?: string;  // a story: what it's about in a sentence or two, shown before it plays
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

/** The two hosts' colours: solid tokens (a gradient is dropped from rings and text). */
export const HOST_TONES = ["var(--t-brand)", "var(--t-host-b)"];
export const HOST_TEXT = ["var(--t-brand-text)", "var(--t-host-b-text)"];

/** An audio story's speakers' colours: the podcast's two, then six more, cycling after eight. */
export const CAST_TONES = [...HOST_TONES, ...[3, 4, 5, 6, 7, 8].map((n) => `var(--t-cast-${n})`)];
export const CAST_TEXT = [...HOST_TEXT, ...[3, 4, 5, 6, 7, 8].map((n) => `var(--t-cast-${n}-text)`)];

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

/** Who is in it on one line: a podcast's two hosts under its title ("Host A and Host B"); a story's cast once its
 * who's-who folds while it plays ("Narrator, The keeper, Ada"). */
export function castLine(m: Media): string {
  const names = (m.hosts ?? []).map((h) => h.name);
  if (!isStory(m)) return names.join(" and ");
  return names.join(", ");
}

/** A story's who's-who line after a name: who they are, else the voice they're read in (a story made before `who`
 * existed), else nothing. { who: "the widow" } → "the widow"; { voice: "Heart" } → "Heart"; neither → "". */
export function castRole(h: Host): string {
  if (h.who) return h.who;
  if (h.voice) return h.voice;
  return "";
}

/**
 * Decides whether a story card shows its who's-who list (a face, name and who for each voice) or folds it to one line.
 * Before it plays the list helps you know who's who; once it plays (or is paused part-way) the faces above the line
 * being said do that, so the list folds and the player stays on a phone's screen, unless you open it again.
 * (live false) → shown; (live, not opened) → folded; (live, opened) → shown.
 */
export function showsWhoIsWho(live: boolean, opened: boolean): boolean {
  if (!live) return true;
  return opened;
}

/** How much the speaking voice's face grows in a story (the others stay at 1). */
export const SPEAKER_SCALE = 1.35;

/** The line being said at `t` and the one before it, for under a story's faces. At 4.5 s in turns starting 0, 2, 4:
 * { before: the turn at 2, now: the turn at 4 }; at 0: { before: null, now: the first }; no transcript: both null. */
export function linesAt(m: Media, t: number): { before: Turn | null; now: Turn | null } {
  const turns = Array.isArray(m.transcript) ? m.transcript : [];
  const i = turnAt(m, t);
  const now = i >= 0 ? turns[i] : null;
  const before = i >= 1 ? turns[i - 1] : null;
  return { before, now };
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
