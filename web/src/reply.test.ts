import { describe, expect, it } from "vitest";
import { replyArrived } from "./reply";

describe("replyArrived", () => {
  const sent = 1000;
  it("is true for a reply after the question", () => {
    expect(replyArrived([{ role: "user", ts: 999 }, { role: "odie", ts: 1001 }], sent)).toBe(true);
  });
  it("is true when the turn stopped for an approval while the app was away", () => {
    expect(replyArrived([{ role: "user", ts: 999 }, { role: "approval", ts: 1002 }], sent)).toBe(true);
  });
  it("is false while only older items exist", () => {
    expect(replyArrived([{ role: "odie", ts: 900 }, { role: "user", ts: 999 }], sent)).toBe(false);
    expect(replyArrived([], sent)).toBe(false);
  });
});

describe("streamStalled", () => {
  it("only a quiet stream in flight counts as stuck", async () => {
    const { streamStalled } = await import("./reply");
    expect(streamStalled(true, 0, 5000)).toBe(true);
    expect(streamStalled(true, 3000, 5000)).toBe(false);   // events came recently: it's alive
    expect(streamStalled(false, 0, 5000)).toBe(false);     // nothing in flight
  });
});

describe("after a tap on a card", () => {
  it("is finished once the server saved the outcome, even an empty one", async () => {
    const { tapFinished } = await import("./reply");
    expect(tapFinished({ status: "approved", result_text: null })).toBe(false);
    expect(tapFinished({ status: "approved", result_text: "" })).toBe(true);
    expect(tapFinished({ status: "approved", result_text: "Sent it." })).toBe(true);
    expect(tapFinished({ status: "expired" })).toBe(true);
  });
});

describe("replyArrived with tools", () => {
  it("doesn't count a step still running (no text, no media yet) as the reply", () => {
    const sent = 1000;
    expect(replyArrived([{ role: "user", ts: 999 }, { role: "odie", ts: 1001, text: "", media: [] }], sent)).toBe(false);
    expect(replyArrived([{ role: "user", ts: 999 }, { role: "odie", ts: 1001, text: "", media: [{ id: "x" }] }], sent)).toBe(true);
    expect(replyArrived([{ role: "user", ts: 999 }, { role: "odie", ts: 1001, text: "Done." }], sent)).toBe(true);
    expect(replyArrived([{ role: "user", ts: 999 }, { role: "approval", ts: 1001, text: "" }], sent)).toBe(true);
  });
});
