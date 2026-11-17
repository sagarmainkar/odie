import { afterEach, describe, expect, it, vi } from "vitest";
import { connectLive, shareLive } from "./live";

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

describe("shareLive", () => {
  it("keeps one stream for every listener and closes it with the last", () => {
    const subscribe = shareLive(() => new FakeSource() as unknown as EventSource);
    const heard: string[] = [];
    const stopA = subscribe({ onEvent: () => heard.push("a") });
    const stopB = subscribe({ onEvent: () => heard.push("b") });
    expect(FakeSource.made.length).toBe(1);
    FakeSource.made[0].onmessage?.({ data: JSON.stringify({ type: "message", text: "hi", ts: 1, session_id: "s" }) });
    expect(heard).toEqual(["a", "b"]);
    stopA();
    expect(FakeSource.made[0].closed).toBe(false);
    stopB();
    expect(FakeSource.made[0].closed).toBe(true);
    subscribe({ onEvent: () => {} });         // a new listener later opens a fresh one
    expect(FakeSource.made.length).toBe(2);
  });

  it("tells every listener when the stream comes back", () => {
    vi.useFakeTimers();
    const subscribe = shareLive(() => new FakeSource() as unknown as EventSource);
    const back: string[] = [];
    subscribe({ onEvent: () => {}, onReconnect: () => back.push("a") });
    subscribe({ onEvent: () => {}, onReconnect: () => back.push("b") });
    FakeSource.made[0].onopen?.();
    FakeSource.made[0].onerror?.();
    vi.advanceTimersByTime(3000);
    FakeSource.made[1].onopen?.();
    expect(back).toEqual(["a", "b"]);
  });
});

describe("shareLive.reopen", () => {
  it("opens the one stream again (the picked personality changed) and keeps its listeners", () => {
    const heard: string[] = [];
    const subscribe = shareLive(() => new FakeSource() as unknown as EventSource);
    const stop = subscribe({ onEvent: (e) => heard.push(e.type) });
    subscribe.reopen();
    expect(FakeSource.made.length).toBe(2);
    expect(FakeSource.made[0].closed).toBe(true);
    FakeSource.made[1].onmessage?.({ data: JSON.stringify({ type: "elsewhere", personality: "abc", what: "reply" }) });
    expect(heard).toEqual(["elsewhere"]);
    stop();
    expect(FakeSource.made[1].closed).toBe(true);
  });

  it("opens nothing while nobody listens", () => {
    const subscribe = shareLive(() => new FakeSource() as unknown as EventSource);
    subscribe.reopen();
    expect(FakeSource.made.length).toBe(0);
  });
});

