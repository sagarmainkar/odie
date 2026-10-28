/** The Notes row in Settings: where the vault is, how many notes are indexed, and how indexing is going. */
export type VaultInfo = {
  // embed_every: minutes between background passes that read new notes and pictures by meaning; 0 is off (5 when absent)
  settings: { dir: string | null; ignore: string[]; embeddings: { provider: string; model: string } | null; embed_every?: number };
  status: { notes: number; chunks: number; vectors: number; model: string | null; scanned_at: string | null; embed_error: string | null } | null;
  progress: { running: boolean; done: number; total: number; phase: "keywords" | "meaning" | "idle"; error: string };
  memory_file?: string;  // where long-term memory really is
  meaning?: { every: number; on: boolean; embedded_at: string | null };  // the background embedding schedule
};

/** The choices for "Update meaning in the background", in minutes; 0 is off. */
export const EMBED_EVERY_CHOICES = [0, 5, 10, 15, 30, 60];

/** The label for one choice: 0 -> "Off"; 15 -> "Every 15 min". */
export function embedEveryLabel(minutes: number): string {
  return minutes === 0 ? "Off" : `Every ${minutes} min`;
}

/**
 * Whether background meaning updates are paused: only when an embedding model is set and the choice is off.
 *   model set, embed_every 0         -> true
 *   model set, embed_every 15        -> false
 *   model set, embed_every absent    -> false (the default, every 5 minutes)
 *   no model, embed_every 0          -> false (there's no meaning to update)
 */
export function meaningPaused(v: VaultInfo): boolean {
  if (!v.settings.embeddings) return false;
  return v.settings.embed_every === 0;
}

export type NotesRow = { sub: string; meta: string; state: "ok" | "busy" | "warn" };

const n = (x: number) => x.toLocaleString("en-US");

export function notesRow(v: VaultInfo): NotesRow | null {
  if (!v.settings.dir) return null;
  const meta = v.settings.dir;
  const p = v.progress;
  if (p.running && p.phase === "keywords" && p.total) return { sub: `Indexing ${n(p.done)} of ${n(p.total)} notes`, meta, state: "busy" };
  if (p.running && p.phase === "meaning" && p.total) return { sub: `Reading by meaning: ${n(p.done)} of ${n(p.total)} passages`, meta, state: "busy" };
  if (p.running) return { sub: "Indexing…", meta, state: "busy" };
  const notes = v.status ? `${n(v.status.notes)} notes` : "Not indexed yet";
  if (meaningPaused(v)) {
    // Searches still read by meaning; only new passages wait: chunks without a vector yet.
    const waiting = v.status ? Math.max(0, v.status.chunks - v.status.vectors) : 0;
    const word = waiting === 1 ? "passage" : "passages";
    const sub = waiting ? `${notes} · meaning updates off · ${n(waiting)} ${word} waiting` : `${notes} · meaning updates off`;
    return { sub, meta, state: "ok" };
  }
  // The index keeps one error for both passes; one that starts "pictures:" belongs to the Photos row.
  const own = (e: string) => (e.startsWith("pictures:") ? "" : e);
  const error = (own(v.status?.embed_error || "") || own(p.error || "")).replace(/^\w+Error: /, "");
  if (/still downloading/.test(error)) return { sub: `${notes} · fetching the embedding model (about 1.5 GB)…`, meta, state: "busy" };  // the first run
  if (error) return { sub: `${notes} · meaning search paused: ${error}`, meta, state: "warn" };
  const model = v.status?.model ? v.status.model.split(":").slice(1).join(":") || v.status.model : "";
  return { sub: model ? `${notes} · keyword + meaning (${model})` : `${notes} · keyword search`, meta, state: "ok" };
}
