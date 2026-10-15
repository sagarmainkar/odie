/** The Notes row in Settings: where the vault is, how many notes are indexed, and how indexing is going. */
export type VaultInfo = {
  settings: { dir: string | null; ignore: string[]; embeddings: { provider: string; model: string } | null };
  status: { notes: number; chunks: number; vectors: number; model: string | null; scanned_at: string | null; embed_error: string | null } | null;
  progress: { running: boolean; done: number; total: number; phase: "keywords" | "meaning" | "idle"; error: string };
  memory_file?: string;  // where long-term memory really is
};

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
  // The index keeps one error for both passes; one that starts "pictures:" belongs to the Photos row.
  const own = (e: string) => (e.startsWith("pictures:") ? "" : e);
  const error = (own(v.status?.embed_error || "") || own(p.error || "")).replace(/^\w+Error: /, "");
  if (/still downloading/.test(error)) return { sub: `${notes} · fetching the embedding model (about 1.5 GB)…`, meta, state: "busy" };  // the first run
  if (error) return { sub: `${notes} · meaning search paused: ${error}`, meta, state: "warn" };
  const model = v.status?.model ? v.status.model.split(":").slice(1).join(":") || v.status.model : "";
  return { sub: model ? `${notes} · keyword + meaning (${model})` : `${notes} · keyword search`, meta, state: "ok" };
}
