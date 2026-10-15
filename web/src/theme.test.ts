import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveLook, timeOfDay } from "./theme";

describe("timeOfDay", () => {
  it("splits the day at 5, 11, 16 and 19", () => {
    expect([4, 5, 10, 11, 15, 16, 18, 19, 23, 0].map(timeOfDay))
      .toEqual(["night", "dawn", "dawn", "noon", "noon", "evening", "evening", "night", "night", "night"]);
  });
});

describe("resolveLook", () => {
  it("auto follows the phone's dark mode, and the clock for the light washes", () => {
    expect(resolveLook("auto", 12, true)).toBe("night");     // dark mode at noon: dark
    expect(resolveLook("auto", 21, false)).toBe("evening");  // light mode at night: never dark
    expect(resolveLook("auto", 8, false)).toBe("dawn");
  });
  it("light never goes to night", () => { expect(resolveLook("light", 21)).toBe("evening"); expect(resolveLook("light", 2)).toBe("dawn"); });
  it("dark is always night", () => { expect(resolveLook("dark", 12)).toBe("night"); });
});

describe("startLookClock", () => {
  afterEach(() => vi.useRealTimers());
  it("re-applies on its interval until stopped", async () => {
    vi.useFakeTimers();
    const { startLookClock } = await import("./theme");
    const apply = vi.fn();
    const stop = startLookClock(1000, apply);
    vi.advanceTimersByTime(3100);
    stop();
    vi.advanceTimersByTime(5000);
    expect(apply).toHaveBeenCalledTimes(3);
  });
});

describe("startLookClock on return", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("re-applies when the app comes back to the screen", async () => {
    const t = new EventTarget() as EventTarget & { visibilityState: string };
    t.visibilityState = "visible";
    vi.stubGlobal("document", t);
    const { startLookClock } = await import("./theme");
    const apply = vi.fn();
    const stop = startLookClock(60_000, apply);
    t.dispatchEvent(new Event("visibilitychange"));
    expect(apply).toHaveBeenCalledTimes(1);
    stop();
    t.dispatchEvent(new Event("visibilitychange"));
    expect(apply).toHaveBeenCalledTimes(1);
  });
});
