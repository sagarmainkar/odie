import { describe, expect, it } from "vitest";
import { ASK_TEXT, NOTE_TEXT, afterAllow, locationRow, seenText, shouldAsk, shouldRefresh, type LocationInfo } from "./location";

const base: LocationInfo = { on: null, place: "", seen: "", home: "", home_set_by_user: false };

describe("location", () => {
  it("asks once, only where the browser can answer", () => {
    expect(shouldAsk(base, true)).toBe(true);
    expect(shouldAsk(base, false)).toBe(false);  // a desktop browser without location: no ask
    expect(shouldAsk({ ...base, on: false }, true)).toBe(false);  // "Not now" is for good
    expect(shouldAsk({ ...base, on: true }, true)).toBe(false);
    expect(shouldAsk(null, true)).toBe(false);
  });

  it("refreshes silently only when allowed", () => {
    expect(shouldRefresh({ ...base, on: true }, true)).toBe(true);
    expect(shouldRefresh({ ...base, on: null }, true)).toBe(false);
    expect(shouldRefresh({ ...base, on: false }, true)).toBe(false);
    expect(shouldRefresh({ ...base, on: true }, false)).toBe(false);
    expect(shouldRefresh(null, true)).toBe(false);
  });

  it("says the place name goes to the model, not that it stays home", () => {
    expect(ASK_TEXT).toContain("place name, not coordinates");
    expect(ASK_TEXT.toLowerCase()).not.toContain("leave");
    expect(ASK_TEXT.toLowerCase()).not.toContain("stays on");
  });

  it("writes the row", () => {
    const now = new Date("2026-10-25T14:16:00+05:30");
    expect(seenText("2026-10-25T14:12:00+05:30", now)).toBe("14:12");
    expect(seenText("2026-10-24T21:40:00+05:30", now)).toBe("Sat 24 Oct 21:40");
    expect(seenText("", now)).toBe("");
    // The place alone on the sub line (a long one truncates there and nothing else is lost); seen and home on a second,
    // shorter line.
    expect(locationRow({ ...base, on: true, place: "City of Northvale, Westshire", seen: "2026-10-25T14:12:00+05:30", home: "Northvale" }, now))
      .toEqual({ sub: "City of Northvale, Westshire", meta: "seen 14:12 · home Northvale", state: "ok" });
    expect(locationRow({ ...base, on: true, place: "Northvale, Westshire", seen: "2026-10-25T14:12:00+05:30" }, now))
      .toEqual({ sub: "Northvale, Westshire", meta: "seen 14:12", state: "ok" });
    expect(locationRow({ ...base, on: true, place: "Northvale, Westshire" }, now)).toEqual({ sub: "Northvale, Westshire", meta: "", state: "ok" });
    expect(locationRow({ ...base, on: true }, now)).toEqual({ sub: "Waiting for the first fix", meta: "", state: "ok" });
    expect(locationRow({ ...base, on: false }, now)).toEqual({ sub: "Off", meta: "", state: "off" });
    expect(locationRow(base, now)).toEqual({ sub: "Not asked yet", meta: "", state: "none" });
  });

  it("keeps the note to one phone line, still naming OpenStreetMap", () => {
    expect(NOTE_TEXT.length).toBeLessThanOrEqual(90);
    expect(NOTE_TEXT).toContain("OpenStreetMap");
    expect(NOTE_TEXT.toLowerCase()).toContain("nearby");
  });
  it("a browser denial ends the ask; a timeout leaves it", () => {
    expect(afterAllow({ lat: 1, lon: 2, at: "2026-10-25T14:12:00+05:30" })).toBe("send");
    expect(afterAllow("denied")).toBe("decline");    // the browser remembers the refusal: asking again would never prompt
    expect(afterAllow(null)).toBe("leave");           // a timeout or no support: the line stays for next time
  });
});
