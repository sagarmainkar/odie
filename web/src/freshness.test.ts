// @vitest-environment jsdom
// The app picks up a new version by itself: it asks the service worker to look for one when the app comes back, on
// focus, when the network returns and every 15 minutes, and reloads only when that loses nothing.
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildDiffers, createFreshness, startUpdateChecks } from "./freshness";

afterEach(() => { vi.useRealTimers(); });

function setVisible(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("update checks", () => {
  it("asks for a new version when the app comes back, on focus, when online again and every 15 minutes while visible", () => {
    vi.useFakeTimers();
    setVisible("visible");
    const update = vi.fn(async () => {});
    const stop = startUpdateChecks({ update, health: async () => null, mine: "a1b2c3d", fresh: createFreshness({ reload: () => {} }) });
    setVisible("hidden");
    expect(update).toHaveBeenCalledTimes(0);  // going away asks nothing
    setVisible("visible");
    expect(update).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("focus"));
    expect(update).toHaveBeenCalledTimes(2);
    window.dispatchEvent(new Event("online"));
    expect(update).toHaveBeenCalledTimes(3);
    vi.advanceTimersByTime(15 * 60 * 1000);
    expect(update).toHaveBeenCalledTimes(4);
    setVisible("hidden");
    vi.advanceTimersByTime(15 * 60 * 1000);
    expect(update).toHaveBeenCalledTimes(4);  // the timer doesn't ask while the app is hidden
    stop();
    setVisible("visible");
    expect(update).toHaveBeenCalledTimes(4);
  });

  it("a server serving another build asks the service worker again; with no service worker it shows the pill", async () => {
    setVisible("visible");
    const update = vi.fn(async () => {});
    const withWorker = createFreshness({ reload: () => {} });
    const stop = startUpdateChecks({ update, health: async () => ({ build: "e4f5a6b" }), mine: "a1b2c3d", fresh: withWorker });
    window.dispatchEvent(new Event("focus"));
    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(2));  // the check, then the one the mismatch asked for
    expect(withWorker.pill()).toBe(false);  // the worker brings the new version; the pill waits for it
    stop();

    const noWorker = createFreshness({ reload: () => {} });
    const stop2 = startUpdateChecks({ update: null, health: async () => ({ build: "e4f5a6b" }), mine: "a1b2c3d", fresh: noWorker });
    window.dispatchEvent(new Event("focus"));
    await vi.waitFor(() => expect(noWorker.pill()).toBe(true));
    stop2();
  });

  it("the same build, the dev server, or a server that doesn't say: nothing to do", () => {
    expect(buildDiffers("a1b2c3d", "e4f5a6b")).toBe(true);
    expect(buildDiffers("a1b2c3d", "a1b2c3d")).toBe(false);
    expect(buildDiffers("dev", "e4f5a6b")).toBe(false);
    expect(buildDiffers("a1b2c3d", undefined)).toBe(false);
    expect(buildDiffers("a1b2c3d", "")).toBe(false);
  });
});

describe("reloading for a new version", () => {
  it("reloads at once when nothing would be lost", () => {
    const reload = vi.fn();
    const fresh = createFreshness({ reload });
    fresh.arrived();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("never reloads mid-answer: it shows the pill and reloads when the answer ends", () => {
    const reload = vi.fn();
    const fresh = createFreshness({ reload });
    fresh.hold("stream", true);
    fresh.arrived();
    expect(reload).not.toHaveBeenCalled();
    expect(fresh.pill()).toBe(true);
    fresh.hold("stream", false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("waits for every hold: an answer, a voice turn, an approval waiting, text in the ask box", () => {
    const reload = vi.fn();
    const fresh = createFreshness({ reload });
    for (const why of ["stream", "voice", "approval", "draft"]) fresh.hold(why, true);
    fresh.arrived();
    for (const why of ["stream", "voice", "approval"]) fresh.hold(why, false);
    expect(reload).not.toHaveBeenCalled();
    fresh.hold("draft", false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("hidden, it reloads over an answer or an approval (both live on the server), never over a voice turn or typed text", () => {
    const reload = vi.fn();
    const streaming = createFreshness({ reload });
    streaming.hold("stream", true);
    streaming.hold("approval", true);
    streaming.arrived();
    streaming.hidden();
    expect(reload).toHaveBeenCalledTimes(1);

    const typed = createFreshness({ reload });
    typed.hold("draft", true);
    typed.hold("voice", true);
    typed.arrived();
    typed.hidden();
    expect(reload).toHaveBeenCalledTimes(1);  // still waits
  });

  it("a tap on the pill reloads whatever holds, and a version reloads only once", () => {
    const reload = vi.fn();
    const fresh = createFreshness({ reload });
    fresh.hold("draft", true);
    fresh.arrived();
    fresh.tap();
    expect(reload).toHaveBeenCalledTimes(1);
    fresh.hold("draft", false);
    fresh.hidden();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("nothing new: a hold ending or the app hiding doesn't reload", () => {
    const reload = vi.fn();
    const fresh = createFreshness({ reload });
    fresh.hold("stream", true);
    fresh.hold("stream", false);
    fresh.hidden();
    expect(reload).not.toHaveBeenCalled();
    expect(fresh.pill()).toBe(false);
  });
});
