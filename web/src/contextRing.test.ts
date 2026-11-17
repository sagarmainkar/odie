import { describe, expect, it } from "vitest";
import { ctxWorthShowing } from "./contextRing";

describe("the header shows how full the conversation is only when it matters", () => {
  it("stays out of a fresh chat's header", () => {
    expect(ctxWorthShowing(2_000, 32_000)).toBe(false);
  });

  it("shows from half full", () => {
    expect(ctxWorthShowing(16_000, 32_000)).toBe(true);
    expect(ctxWorthShowing(30_000, 32_000)).toBe(true);
  });

  it("stays out while the limit isn't known", () => {
    expect(ctxWorthShowing(5_000, 0)).toBe(false);
  });
});
