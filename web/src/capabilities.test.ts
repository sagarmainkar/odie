import { describe, expect, it } from "vitest";
import { has, shown, tabFor } from "./capabilities";
import { IDEAS, ideasFor } from "./ideas";

describe("capabilities", () => {
  it("shows everything while they aren't known", () => {
    expect(has(null, "money")).toBe(true);
    expect(ideasFor(null)).toEqual(IDEAS);
    expect(tabFor("money", null)).toBe("money");
  });

  it("drops what the install doesn't have", () => {
    const caps = new Set(["vault"]);
    expect(has(caps, "calendar")).toBe(false);
    const asks = ideasFor(caps).map((i) => i.q);
    expect(asks).not.toContain("What's on today?");
    expect(asks).not.toContain("Anything in mail I should answer?");
    expect(asks).not.toContain("What did I spend this week?");
    expect(asks).toContain("Plan a weekend trip for me");
    expect(asks).toContain("What can you do?");
  });

  it("keeps what's there", () => {
    const caps = new Set(["mail", "calendar", "google", "money"]);
    expect(ideasFor(caps)).toEqual(IDEAS);
    expect(shown([{ needs: "money" }, {}], new Set<string>())).toEqual([{}]);
  });

  it("sends the Money tab to Today without a ledger", () => {
    expect(tabFor("money", new Set(["mail"]))).toBe("today");
    expect(tabFor("money", new Set(["money"]))).toBe("money");
    expect(tabFor("chat", new Set<string>())).toBe("chat");
  });
});
