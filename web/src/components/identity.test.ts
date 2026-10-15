import { describe, expect, it } from "vitest";
import { avatarMode } from "./Avatar";
import { moodClass } from "./Orb";
import { toolTile } from "./Tile";

describe("avatarMode", () => {
  it("uses the photo only when there is one and it loaded", () => {
    expect(avatarMode("/api/persona/avatar/1", false)).toBe("photo");
    expect(avatarMode(null, false)).toBe("orb");
    expect(avatarMode("", false)).toBe("orb");
    expect(avatarMode("/api/persona/avatar/1", true)).toBe("orb");
  });
});

describe("toolTile", () => {
  it("maps known tools and falls back for unknown ones", () => {
    expect(toolTile("gmail_search")).toEqual({ icon: "mail", color: "blue" });
    expect(toolTile("life_admin")).toEqual({ icon: "rupee", color: "green" });
    expect(toolTile("market_history")).toEqual({ icon: "chart", color: "violet" });
    expect(toolTile("run_shell")).toEqual({ icon: "terminal", color: "ink" });
    expect(toolTile("something_new")).toEqual({ icon: "spark", color: "violet" });
  });
});

describe("moodClass", () => {
  it("idle breathes; other states name themselves", () => {
    expect(moodClass("idle")).toBe("breathe");
    expect(moodClass("speaking")).toBe("is-speaking");
    expect(moodClass("thinking")).toBe("is-thinking");
  });
});
