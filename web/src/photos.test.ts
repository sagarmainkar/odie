import { describe, expect, it } from "vitest";
import { photosRow, type PhotosInfo } from "./photos";

const base: PhotosInfo = {
  settings: { on: true, screenshots: false },
  status: { photos: 9966, videos: 1170, photo_vectors: 0, photos_at: "2026-10-14T17:00:00" },
  progress: { running: false, done: 0, total: 0, phase: "idle", error: "" },
};

describe("photosRow", () => {
  it("offers to turn photos on when they are off", () => {
    const r = photosRow({ ...base, settings: { on: false, screenshots: false }, status: null });
    expect(r.state).toBe("off");
    expect(r.sub).toBe("Off. Find your photos and videos by who, where and when");
  });

  it("counts while the library is read", () => {
    const r = photosRow({ ...base, status: null, progress: { running: true, done: 3000, total: 10794, phase: "photos", error: "" } });
    expect(r.sub).toBe("Reading your library: 3,000 of 10,794");
    expect(r.state).toBe("busy");
  });

  it("says what it knows when idle, screenshots included or not", () => {
    expect(photosRow(base).sub).toBe("9,966 photos · 1,170 videos · people, places, things, dates");
    expect(photosRow(base).state).toBe("ok");
    expect(photosRow({ ...base, settings: { on: true, screenshots: true } }).sub).toBe("9,966 photos · 1,170 videos · people, places, things, dates · screenshots too");
  });

  it("says how pictures get meaning", () => {
    expect(photosRow({ ...base, meaning: "gemma" }).sub).toBe("9,966 photos · 1,170 videos · people, places, things, dates · by meaning");
    expect(photosRow({ ...base, meaning: "text" }).sub).toBe("9,966 photos · 1,170 videos · people, places, things, dates · pictures by meaning need EmbeddingGemma 2 on this Mac");
    expect(photosRow({ ...base, meaning: "none" }).sub).toBe("9,966 photos · 1,170 videos · people, places, things, dates");
    const r = photosRow({ ...base, meaning: "gemma", progress: { running: true, done: 800, total: 7912, phase: "pictures", error: "" } });
    expect(r.sub).toBe("Reading pictures by meaning: 800 of 7,912");
    expect(r.state).toBe("busy");
  });

  it("waits for the first read, and shows a library error plainly", () => {
    expect(photosRow({ ...base, status: { ...base.status!, photos: 0, videos: 0, photos_at: null } }).sub).toBe("Reading your library soon");
    const r = photosRow({ ...base, progress: { ...base.progress, error: "Photos: macOS didn't let Odie read the Photos library." } });
    expect(r.state).toBe("warn");
    expect(r.sub).toBe("macOS didn't let Odie read the Photos library.");
  });
});

describe("photosRow and a paused picture pass", () => {
  it("says the pictures paused, with the reason", () => {
    const r = photosRow({ ...base, meaning: "gemma", progress: { ...base.progress, error: "pictures: EmbedError: gemma said 400: couldn't open a picture" } });
    expect(r.state).toBe("warn");
    expect(r.sub).toBe("pictures by meaning paused: gemma said 400: couldn't open a picture");
  });
});
