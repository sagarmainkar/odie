import { describe, expect, it } from "vitest";
import { ago, askAbout } from "./news";

const now = new Date("2026-10-05T06:00:00Z");

describe("ago", () => {
  it("reads like a person would say it", () => {
    expect(ago("2026-10-05T05:59:30Z", now)).toBe("just now");
    expect(ago("2026-10-05T05:15:00Z", now)).toBe("45 min ago");
    expect(ago("2026-10-05T03:00:00Z", now)).toBe("3h ago");
    expect(ago("2026-10-04T05:00:00Z", now)).toBe("yesterday");
    expect(ago("2026-10-02T05:00:00Z", now)).toBe("3 days ago");
  });
  it("says nothing for missing or bad times", () => {
    expect(ago(null, now)).toBe("");
    expect(ago("not a date", now)).toBe("");
  });
});

describe("askAbout", () => {
  it("names the story and its link", () => {
    expect(askAbout({ title: "RBI holds rates", link: "https://x.com/a", source: "Mint", topic: "Markets", published: null, image: null }))
      .toBe("Tell me more about this story: RBI holds rates (https://x.com/a)");
  });
});
