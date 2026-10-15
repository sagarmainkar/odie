import { describe, expect, it } from "vitest";
import { codeFromHash, lastSeen, loopback, needsPairing, needsPasscode, typedCode, watchPrivate } from "./devices";

const now = Date.UTC(2026, 9, 6, 12, 0, 0);
const ago = (s: number) => now / 1000 - s;

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("devices", () => {
  it("reads the code a pairing link carries", () => {
    expect(codeFromHash("#pair=ABCD-EFGH")).toBe("ABCD-EFGH");
    expect(codeFromHash("#pair=abcdefgh")).toBe("ABCD-EFGH");
    expect(codeFromHash("#settings")).toBeNull();
    expect(codeFromHash("#pair=ABC")).toBeNull();
    expect(codeFromHash("")).toBeNull();
  });

  it("shows a typed code in capitals with a dash after four", () => {
    expect(typedCode("abcd")).toBe("ABCD");
    expect(typedCode("abcde")).toBe("ABCD-E");
    expect(typedCode("ab cd-ef gh ij")).toBe("ABCD-EFGH");
  });

  it("says when a device was last seen", () => {
    expect(lastSeen(ago(30), now)).toBe("Active now");
    expect(lastSeen(ago(5 * 60), now)).toBe("5 minutes ago");
    expect(lastSeen(ago(3600), now)).toBe("An hour ago");
    expect(lastSeen(ago(3 * 3600), now)).toBe("3 hours ago");
    expect(lastSeen(ago(30 * 3600), now)).toBe("Yesterday");
    expect(lastSeen(ago(4 * 86400), now)).toBe("4 days ago");
    expect(lastSeen(ago(40 * 86400), now)).toMatch(/\d/);
  });

  it("needs pairing only while pairing is on and this browser isn't paired", () => {
    expect(needsPairing({ on: true, paired: false, devices: 1, passcode: true })).toBe(true);
    expect(needsPairing({ on: true, paired: true, devices: 1, passcode: true })).toBe(false);
    expect(needsPairing({ on: false, paired: false, devices: 0, passcode: false })).toBe(false);
    expect(needsPairing(null)).toBe(false);
  });

  it("asks for a recovery passcode while pairing is on and none was made", () => {
    expect(needsPasscode({ on: true, paired: true, devices: 1, passcode: false })).toBe(true);
    expect(needsPasscode({ on: true, paired: true, devices: 1, passcode: true })).toBe(false);
    expect(needsPasscode({ on: false, paired: false, devices: 0, passcode: false })).toBe(false);
    expect(needsPasscode(null)).toBe(false);
  });

  it("knows a link to this computer itself can't be opened elsewhere", () => {
    expect(loopback("http://localhost:8000/#pair=ABCD-EFGH")).toBe(true);
    expect(loopback("http://127.0.0.1:8011/#pair=ABCD-EFGH")).toBe(true);
    expect(loopback("http://[::1]:8000/")).toBe(true);
    expect(loopback("https://mac.tail1234.ts.net/#pair=ABCD-EFGH")).toBe(false);
    expect(loopback("http://192.168.1.20:8000/")).toBe(false);
  });

  it("notices when an API says this Odie is private", async () => {
    let told = 0;
    const answers = [reply(401, { detail: "This Odie is private.", pair: true }), reply(401, { detail: "That code didn't work." }), reply(200, { ok: true })];
    const f = watchPrivate(async () => answers.shift()!, () => { told += 1; });
    const first = await f("/api/tasks");
    expect(first.status).toBe(401);
    expect((await first.json()).pair).toBe(true);  // the caller can still read the body
    await f("/api/pair/code");
    await f("/api/tasks");
    expect(told).toBe(1);
  });
});
