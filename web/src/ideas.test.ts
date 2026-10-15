import { describe, expect, it } from "vitest";
import { ideasFor } from "./ideas";

describe("new-chat ideas", () => {
  it("starts with what Odie can do, then a weekend trip", () => {
    const qs = ideasFor(null, "IN").map((i) => i.q);
    expect(qs[0]).toBe("What can you do?");
    expect(qs[1]).toBe("Plan a weekend trip for me");
  });

  it("asks about the market where the user is, and none where it can't tell", () => {
    const q = (country: string) => ideasFor(null, country).map((i) => i.q).filter((x) => /doing this week/.test(x));
    expect(q("IN")).toEqual(["How is NIFTY doing this week?"]);
    expect(q("US")).toEqual(["How is the NASDAQ doing this week?"]);
    expect(q("FR")).toEqual([]);
    expect(q("")).toEqual([]);
  });
});
