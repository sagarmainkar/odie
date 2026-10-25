/** The Photos row in Settings: what /api/photos says, as one line and a state. */
export type PhotosInfo = {
  settings: { on: boolean; screenshots: boolean };
  status: { photos: number; videos: number; photo_vectors: number; photos_at: string | null } | null;
  progress: { running: boolean; done: number; total: number; phase: string; error: string };
  meaning?: "gemma" | "text" | "none";  // how pictures get meaning: an EmbeddingGemma 2 that sees them (Odie's service, Ollama); a text-only embedder can't; none set
};
export type PhotosRow = { sub: string; state: "off" | "busy" | "ok" | "warn" };

const n = (x: number) => x.toLocaleString("en-US");

/**
 * One line for the row. Worked examples:
 *   off                                  -> "Off. Find your photos and videos by who, where and when" (state off)
 *   on, the library being read           -> "Reading your library: 3,000 of 10,794" (busy)
 *   on, pictures being read by meaning   -> "Reading pictures by meaning: 800 of 7,912" (busy)
 *   on, read, meaning by Gemma           -> "9,966 photos · 1,170 videos · people, places, things, dates · by meaning" (ok)
 *   on, read, a text-only embedder       -> "… · pictures by meaning need EmbeddingGemma 2 (Odie's service, or on Ollama)" (ok)
 *   on, the pass said macOS refused      -> that reason, without the "Photos: " prefix (warn)
 *   on, the picture pass failed          -> "pictures by meaning paused: <reason>" (warn)
 */
export function photosRow(v: PhotosInfo): PhotosRow {
  if (!v.settings.on) return { sub: "Off. Find your photos and videos by who, where and when", state: "off" };
  const p = v.progress;
  if (p.running && p.phase === "photos") {
    return { sub: p.total ? `Reading your library: ${n(p.done)} of ${n(p.total)}` : "Reading your library…", state: "busy" };
  }
  if (p.running && p.phase === "pictures") {
    return { sub: p.total ? `Reading pictures by meaning: ${n(p.done)} of ${n(p.total)}` : "Reading pictures by meaning…", state: "busy" };
  }
  const problem = (p.error.split("; ").find((e) => e.startsWith("Photos: ")) ?? "").replace(/^Photos: /, "");
  if (problem) return { sub: problem, state: "warn" };
  const paused = (p.error.split("; ").find((e) => e.startsWith("pictures:")) ?? "").replace(/^pictures:\s*(\w+Error:\s*)?/, "");
  if (paused) return { sub: `pictures by meaning paused: ${paused}`, state: "warn" };
  if (!v.status || !v.status.photos_at) return { sub: "Reading your library soon", state: "busy" };
  const parts = [`${n(v.status.photos)} photos`, `${n(v.status.videos)} videos`, "people, places, things, dates"];
  if (v.meaning === "gemma") parts.push("by meaning");
  if (v.meaning === "text") parts.push("pictures by meaning need EmbeddingGemma 2 (Odie's service, or on Ollama)");
  if (v.settings.screenshots) parts.push("screenshots too");
  return { sub: parts.join(" · "), state: "ok" };
}
