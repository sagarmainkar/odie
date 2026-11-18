import { describe, expect, it } from "vitest";
import { proactiveSub, proactiveUrl, showsProactive } from "./proactive";

describe("Proactive intelligence, per personality", () => {
  it("asks for whoever is picked", () => {
    expect(proactiveUrl("abc")).toBe("/api/proactive?personality=abc");
  });

  it("shows the switch only for a personality with an inbox of its own", () => {
    expect(showsProactive("abc", { offered: true, on: false, apps: ["work"] })).toBe(true);
    expect(showsProactive("abc", { offered: false, on: false, apps: [] })).toBe(false);
    expect(showsProactive("", { offered: true, on: false, apps: ["work"] })).toBe(false);
    expect(showsProactive("abc", null)).toBe(false);
  });

  it("says what it does in either position", () => {
    expect(proactiveSub({ offered: true, on: true, apps: ["work-mail"] })).toBe("Checks work-mail every 30 minutes and puts what needs you on its Pulse.");
    expect(proactiveSub({ offered: true, on: false, apps: ["work-mail"] })).toBe("Off: it reads work-mail only when you ask in chat.");
  });
});
