import { describe, expect, it } from "vitest";
import { shrunkSize, worthShrinking } from "./shrinkPhoto";

describe("shrunkSize", () => {
  it("brings a phone photo's long edge down to 1280, keeping its shape", () => {
    expect(shrunkSize(4032, 3024)).toEqual({ width: 1280, height: 960 });
    expect(shrunkSize(3024, 4032)).toEqual({ width: 960, height: 1280 });
  });

  it("never makes a small picture bigger", () => {
    expect(shrunkSize(800, 600)).toEqual({ width: 800, height: 600 });
    expect(shrunkSize(1280, 720)).toEqual({ width: 1280, height: 720 });
  });
});

describe("worthShrinking", () => {
  it("shrinks big photos only", () => {
    expect(worthShrinking({ size: 5_000_000, type: "image/jpeg" })).toBe(true);
    expect(worthShrinking({ size: 3_000_000, type: "image/heic" })).toBe(true);
    expect(worthShrinking({ size: 200_000, type: "image/png" })).toBe(false);
    expect(worthShrinking({ size: 5_000_000, type: "application/pdf" })).toBe(false);
  });
});
