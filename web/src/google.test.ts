import { describe, expect, it } from "vitest";
import { googleRows, renewBy, splitConnect } from "./google";

describe("google", () => {
  it("says what each service is doing and offers the fix", () => {
    expect(googleRows(null, false).action).toBe("Connect Google");
    expect(googleRows({ gmail: "ok", calendar: "ok" }, true)).toEqual({ gmail: "Connected", calendar: "Connected", action: null, ok: true });
    expect(googleRows({ gmail: "ok", calendar: "calendar" }, true).action).toBe("Add Calendar");
    expect(googleRows({ gmail: "expired", calendar: "expired" }, true)).toMatchObject({ gmail: "Login expired", action: "Reconnect", ok: false });
  });
  it("knows when to renew", () => {
    expect(renewBy("2026-10-05T10:00:00Z")).toMatch(/12 Oct/);
    expect(renewBy(null)).toBe("");
  });
  it("finds the Connect card in a message", () => {
    expect(splitConnect("Your Google login has expired. Tap Connect Google to fix it. [connect:google]"))
      .toEqual({ text: "Your Google login has expired. Tap Connect Google to fix it.", connect: true });
    expect(splitConnect("Hello").connect).toBe(false);
  });
});
