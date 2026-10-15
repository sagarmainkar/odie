import { describe, expect, it } from "vitest";
import { notesRow, type VaultInfo } from "./vault";

const base: VaultInfo = {
  settings: { dir: "/Users/asha/Notes", ignore: [], embeddings: null },
  status: { notes: 1280, chunks: 4000, vectors: 0, model: null, scanned_at: "2026-10-06T21:00:00", embed_error: null },
  progress: { running: false, done: 0, total: 0, phase: "idle", error: "" },
};

describe("notesRow", () => {
  it("is absent without a folder", () => {
    expect(notesRow({ ...base, settings: { dir: null, ignore: [], embeddings: null }, status: null })).toBeNull();
  });

  it("counts notes while the keyword pass runs", () => {
    const r = notesRow({ ...base, progress: { running: true, done: 312, total: 1280, phase: "keywords", error: "" } })!;
    expect(r.sub).toBe("Indexing 312 of 1,280 notes");
    expect(r.state).toBe("busy");
  });

  it("counts passages while meaning is read", () => {
    const r = notesRow({ ...base, settings: { ...base.settings, embeddings: { provider: "ollama", model: "nomic-embed-text" } },
                         progress: { running: true, done: 120, total: 900, phase: "meaning", error: "" } })!;
    expect(r.sub).toBe("Reading by meaning: 120 of 900 passages");
  });

  it("says keyword only, or keyword and meaning, when idle", () => {
    expect(notesRow(base)!.sub).toBe("1,280 notes · keyword search");
    const meaning = notesRow({ ...base, status: { ...base.status!, vectors: 4000, model: "ollama:nomic-embed-text" } })!;
    expect(meaning.sub).toBe("1,280 notes · keyword + meaning (nomic-embed-text)");
    expect(meaning.state).toBe("ok");
    expect(meaning.meta).toBe("/Users/asha/Notes");
  });

  it("shows an error plainly", () => {
    const r = notesRow({ ...base, status: { ...base.status!, embed_error: "EmbedError: couldn't reach ollama" } })!;
    expect(r.state).toBe("warn");
    expect(r.sub).toBe("1,280 notes · meaning search paused: couldn't reach ollama");
  });
});

describe("notesRow and the pictures' own error", () => {
  it("leaves a paused picture pass to the Photos row", async () => {
    const { notesRow } = await import("./vault");
    const r = notesRow({ ...base, status: { ...base.status!, vectors: 4000, model: "gemma:google/embeddinggemma-2", embed_error: "pictures: EmbedError: gemma said 400" },
                         progress: { running: false, done: 0, total: 0, phase: "idle", error: "pictures: EmbedError: gemma said 400" } })!;
    expect(r.state).toBe("ok");
    expect(r.sub).toBe("1,280 notes · keyword + meaning (google/embeddinggemma-2)");
  });
});

describe("notesRow while the embedding model downloads", () => {
  it("counts it as busy, not broken", async () => {
    const { notesRow } = await import("./vault");
    const r = notesRow({ ...base, settings: { ...base.settings, embeddings: { provider: "gemma", model: "google/embeddinggemma-2" } },
                         progress: { running: false, done: 0, total: 0, phase: "idle", error: "EmbedError: the embedding model is still downloading (about 1.5 GB); Odie tries again in a few minutes" } })!;
    expect(r.state).toBe("busy");
    expect(r.sub).toBe("1,280 notes · fetching the embedding model (about 1.5 GB)…");
  });
});
