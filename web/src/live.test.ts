import { afterEach, describe, expect, it, vi } from "vitest";
import { connectLive } from "./live";

class FakeSource {
  static made: FakeSource[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() { FakeSource.made.push(this); }
  close() { this.closed = true; }
}

afterEach(() => { vi.useRealTimers(); FakeSource.made = []; });

describe("connectLive", () => {
  it("does not reopen after it was stopped while a reconnect was pending", () => {
    vi.useFakeTimers();
    const stop = connectLive(() => new FakeSource() as unknown as EventSource, () => {});
    FakeSource.made[0].onerror?.();          // the phone went to the background: the stream errors
    stop();                                   // the screen re-subscribed (handlers changed) before the retry
    vi.advanceTimersByTime(5000);
    expect(FakeSource.made.length).toBe(1);   // no orphan connection delivering every event a second time
  });

  it("reconnects after an error while still subscribed, and keeps only one open", () => {
    vi.useFakeTimers();
    const stop = connectLive(() => new FakeSource() as unknown as EventSource, () => {});
    FakeSource.made[0].onerror?.();
    vi.advanceTimersByTime(3000);
    expect(FakeSource.made.length).toBe(2);
    expect(FakeSource.made.filter((s) => !s.closed).length).toBe(1);
    stop();
    expect(FakeSource.made.every((s) => s.closed)).toBe(true);
  });
});
