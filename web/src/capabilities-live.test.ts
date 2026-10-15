import { describe, expect, it, vi } from "vitest";

// useCaps as a plain call, with React's hooks stubbed: it must not open its own live event stream (each EventSource
// holds one of the browser's six HTTP/1.1 connections to this host).
const live = vi.hoisted(() => ({ calls: 0 }));
vi.mock("./live", () => ({ useLive: () => { live.calls += 1; } }));
vi.mock("react", () => ({
  useState: (v: unknown) => [v, () => {}],
  useEffect: () => {},
  useCallback: (f: unknown) => f,
}));

describe("useCaps", () => {
  it("opens no live stream of its own", async () => {
    const { useCaps } = await import("./capabilities");
    expect(useCaps()).toBeNull();
    expect(live.calls).toBe(0);
  });
});
